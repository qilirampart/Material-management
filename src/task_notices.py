"""Non-blocking summaries for foreground work and background task outcomes."""
from dataclasses import dataclass
from uuid import uuid4
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QMenu, QPushButton, QStyle, QSystemTrayIcon


@dataclass(frozen=True)
class Notice:
    key: str
    destination: int
    title: str
    detail: str
    attention: bool


class NoticeFeed:
    def __init__(self):
        self.items=[]
        self.unread=set()

    def add(self,notice,visible):
        if any(item.key==notice.key for item in self.items):
            return False
        self.items.insert(0,notice)
        if not visible:
            self.unread.add(notice.key)
        if len(self.items)>30:
            self.unread.discard(self.items.pop().key)
        return not visible


class TaskNotices(QObject):
    def __init__(self,window,rail):
        super().__init__(window)
        self.window=window
        self.feed=NoticeFeed()
        self.button=QPushButton('任务提醒')
        self.button.setStyleSheet('margin: 8px 14px 12px; padding: 8px')
        self.menu=QMenu(self.button)
        self.menu.aboutToShow.connect(self.populate)
        self.button.setMenu(self.menu)
        rail.addWidget(self.button)
        self.tray=None
        self.pending={}
        self.shown=None
        self.timer=QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.flush)

    def visible(self,destination):
        w=self.window
        return (w.isVisible() and not w.isMinimized() and w.isActiveWindow() and
                ((destination==-1 and w.navigation.currentRow()==0) or
                 (w.navigation.currentRow()==4 and w.recreation.tabs.currentIndex()==destination)))

    def add(self,destination,title,detail,*,key=None,attention=False):
        if self.window.close_after:
            return
        n=Notice(key or uuid4().hex,destination,title,detail,attention)
        if self.feed.add(n,self.visible(destination)):
            self.button.setText(f'任务提醒 · {len(self.feed.unread)}')
            if self.window.config.get('desktop_notices',True):
                self.pending[n.key]=n
                if not self.timer.isActive():
                    self.timer.start(1600)

    def populate(self):
        self.menu.clear()
        if not self.feed.items:
            self.menu.addAction('暂无任务提醒').setEnabled(False)
        for n in self.feed.items[:12]:
            action=self.menu.addAction(n.title+' · '+n.detail.replace('\n',' ')[:64])
            action.triggered.connect(lambda _=False, item=n:self.open(item))
        self.feed.unread.clear()
        self.pending.clear()
        self.button.setText('任务提醒')

    def open(self,notice):
        if not notice:
            return
        w=self.window
        if w.isMinimized():
            w.showNormal()
        w.show()
        w.raise_()
        w.activateWindow()
        w.navigation.setCurrentRow(0 if notice.destination==-1 else 4)
        if notice.destination>=0:
            w.recreation.tabs.setCurrentIndex(notice.destination)
        self.feed.unread.discard(notice.key)
        self.pending.pop(notice.key, None)
        self.button.setText('任务提醒'+(f' · {len(self.feed.unread)}' if self.feed.unread else ''))

    def flush(self):
        items=list(self.pending.values())
        self.pending.clear()
        items=[n for n in items if not self.visible(n.destination)]
        if not items or not self.window.config.get('desktop_notices',True):
            return
        if not (QSystemTrayIcon.isSystemTrayAvailable() and QSystemTrayIcon.supportsMessages()):
            return  # history is still accessible from the rail
        if self.tray is None:
            icon=self.window.windowIcon()
            if icon.isNull():
                icon=self.window.style().standardIcon(QStyle.SP_ComputerIcon)
            self.tray=QSystemTrayIcon(icon,self.window)
            self.tray.setToolTip('点众素材投放助手 · 任务提醒')
            self.tray.messageClicked.connect(lambda:self.open(self.shown))
            self.tray.show()
        self.shown=next((n for n in reversed(items) if n.attention),items[-1])
        extra=f'（另有 {len(items)-1} 条）' if len(items)>1 else ''
        self.tray.showMessage(self.shown.title+extra,self.shown.detail,QSystemTrayIcon.Information,7000)
