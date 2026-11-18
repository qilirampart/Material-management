"""Offline diagnostic for the packaged native application."""
import json
import threading
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from src.desktop import MainWindow, configure_app
from src.media import run
from src.ui_design import Background


def smoke(output):
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    configure_app(app)
    window = MainWindow(restore=False)
    window.show()
    result = {};completed=False;stop=threading.Event();task=None;preview=None

    def finish():
        try:
            for i, name in enumerate(["tasks", "review", "platform", "settings","recreation"]):
                window.navigation.setCurrentRow(i)
                app.processEvents()
                window.grab().save(str(folder / (name + ".png")))
            if window.recreation.tabs.tabText(5) != '06  文件清理':
                raise ValueError('Cleanup workflow page is missing')
            window.recreation.tabs.setCurrentIndex(5)
            app.processEvents()
            window.grab().save(str(folder/'file-cleanup.png'))
            result['cleanup_page'] = True
            # Load a local page in the real embedded browser. No external site or login.
            from PySide6.QtWebEngineWidgets import QWebEngineView
            browser = QWebEngineView(window)
            browser.loadFinished.connect(browser_loaded)
            browser.setHtml("<html><body><h1>Desktop browser ready</h1></body></html>")
            result["browser"] = browser
        except Exception as exc:
            save(False, str(exc))

    def browser_loaded(ok):
        nonlocal task
        try:
            if not ok:save(False,'Embedded browser did not load');return
            result['ffmpeg']=run(["ffmpeg", "-version"]).splitlines()[0]
            def processing():
                from src.material_variants import VariantOptions,generate_variants
                source=folder/'diagnostic-source.mp4';captions=folder/'diagnostic.srt'
                captions.write_text('1\n00:00:01,000 --> 00:00:03,000\n字幕与画面验收\n',encoding='utf-8')
                run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=size=320x240:rate=30:duration=4',
                    '-f','lavfi','-i','sine=frequency=440:duration=4','-c:v','libx264','-c:a','aac','-shortest',str(source)],should_stop=stop.is_set)
                reports={}
                for mode in ('md5','micro'):
                    options=VariantOptions(mode=mode,uploader='TEST',clip_mode='range',range_start=1,range_duration=2,
                        grid_layout='quad',picture_style='sepia',border_width=4,subtitle_path=str(captions),
                        cover_mode='frame',cover_time=1,title='候选版验收')
                    report=generate_variants([{'path':str(source),'video_id':'diagnostic','drama':'本地验收'}],folder/mode,
                        options,should_stop=stop.is_set)
                    if report['failed'] or report['stopped'] or len(report['outputs'])!=1:raise ValueError(str(report))
                    reports[mode]=report
                reports['cleanup'] = cleanup_smoke(source, reports['micro']['outputs'][0]['path'], folder)
                return reports
            task=Background(processing,window)
            task.result.connect(lambda value:result.update(processing=value))
            task.failed.connect(lambda value:result.update(error=value))
            task.finished.connect(processing_finished);task.start()
        except Exception as exc:
            save(False, str(exc))

    def processing_finished():
        nonlocal preview
        if result.get('error') or stop.is_set():save(False,result.get('error','Diagnostic stopped'));return
        try:
            from src.micro_preview import MicroPreviewDialog
            output=result['processing']['micro']['outputs'][0]
            preview=MicroPreviewDialog({'path':output['path'],'clip_start':1,'metadata':output['metadata']},window)
            preview.show();preview.player.play()
            QTimer.singleShot(2000,playback_finished)
        except Exception as exc:save(False,str(exc))

    def playback_finished():
        if completed:return
        if preview is None or preview.video.frame.isNull():save(False,'Embedded player did not decode a frame');return
        preview.player.pause();preview.grab().save(str(folder/'micro-playback.png'))
        preview.video.frame.save(str(folder/'micro-frame.png'));save(True,'Browser, bundled FFmpeg, processing and playback ready')

    def save(ok, message):
        nonlocal completed
        if completed:return
        completed=True
        if preview is not None:preview.done(0)
        report={key:value for key,value in result.items() if key!='browser'}
        report.update(ok=ok,pages=window.pages.count(),message=message)
        (folder / "result.json").write_text(json.dumps(report, ensure_ascii=False,indent=2), encoding="utf-8")
        window.close()
        app.exit(0 if ok else 1)

    def timeout():
        if completed:return
        stop.set()
        if task is None or not task.isRunning():save(False,'Diagnostic timed out')

    QTimer.singleShot(250, finish)
    QTimer.singleShot(90000,timeout)
    return app.exec()


def cleanup_smoke(source, product, evidence_root):
    """Check the packaged cleanup module against owned, temporary real media."""
    import shutil
    import tempfile
    from src.recreation import RecreationBatch
    from src.recreation_workspace import RecreationWorkspace
    from src.recreation_cleanup import plan_selection, execute_cleanup
    with tempfile.TemporaryDirectory(prefix='cleanup-smoke-', dir=evidence_root) as temp:
        root = Path(temp)
        workspace = RecreationWorkspace(root/'workspace.json', root)
        missing, healthy = workspace.create('4100-旧批次\n4200-可用批次')
        for batch in (missing, healthy):
            batch.record_page(batch.state['dramas'][0], [{'id': '1', 'name': '二创'}], 1)
            workspace.add_inputs('md5', batch.folder, [batch.state['sources'][0]['video_id']])
        (missing.folder/'recreation.json').rename(missing.folder/'record.test-backup')
        if len(workspace.resolve_inputs('md5')) != 1:
            raise ValueError('Missing batch blocked valid processing input')
        item = healthy.state['sources'][0]
        raw = healthy.download_target(item); raw.parent.mkdir(parents=True)
        shutil.copyfile(source, raw)
        item.update(path=str(raw.resolve()), download_status='downloaded')
        output = healthy.folder/'加工成品'/'run'/'video.mp4'; output.parent.mkdir(parents=True)
        shutil.copyfile(product, output)
        healthy.add_outputs([{'path': str(output), 'drama': '可用批次', 'mode': 'micro', 'metadata': {}}])
        result = execute_cleanup(plan_selection(root, [healthy.folder], [output]), workspace)
        if result['errors'] or output.exists() or not raw.is_file():
            raise ValueError('Product cleanup did not preserve original video')
        result = execute_cleanup(plan_selection(root, [healthy.folder], [raw]), workspace)
        if result['errors'] or raw.exists() or workspace.resolve_inputs('md5'):
            raise ValueError('Original cleanup did not sync processing input')
        return {'ok': True, 'missing_batch_isolated': True, 'media_and_records_synced': True}
