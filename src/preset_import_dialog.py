"""Review shared recipes before adding them to the local favorites library."""
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QTreeWidget,QTreeWidgetItem,QComboBox
from src.micro_presets import preset_references
from src.ui_design import btn,label


class PresetImportDialog(QDialog):
    def __init__(self,incoming,local,parent=None):
        super().__init__(parent)
        self.setWindowTitle('导入创新方案');self.resize(640,480)
        self.incoming=incoming;self.local=local
        outer=QVBoxLayout(self);outer.addWidget(label('导入创新方案','heading'))
        outer.addWidget(label('仅加入收藏，不切换当前参数；图片、音乐等资源文件不会随方案复制。'))
        self.tree=QTreeWidget();self.tree.setHeaderLabels(['方案／引用资源','状态'])
        self.tree.setColumnWidth(0,400);outer.addWidget(self.tree,1)
        self.nodes=[];missing=0
        for name,values in incoming.items():
            node=QTreeWidgetItem([name,'']);self.tree.addTopLevelItem(node);self.nodes.append((name,node))
            refs=preset_references(values)
            for ref in refs:
                child=QTreeWidgetItem([ref['label']+' · '+ref['path'].replace('\\','/').rsplit('/',1)[-1],
                    '本机存在' if ref['exists'] else '缺少，需重新选择'])
                child.setToolTip(0,ref['path']);node.addChild(child)
                missing+=not ref['exists']
            node.setExpanded(any(not ref['exists'] for ref in refs))
        outer.addWidget(label(f'{len(incoming)} 个方案 · {missing} 项引用资源缺失'))
        self.policy=QComboBox();self.policy.addItem('同名时保留两份，为导入项自动编号',False)
        self.policy.addItem('替换本机同名收藏',True);outer.addWidget(self.policy)
        self.policy.currentIndexChanged.connect(self.refresh_conflicts);self.refresh_conflicts()
        row=QHBoxLayout();row.addStretch();row.addWidget(btn('取消',self.reject))
        row.addWidget(btn(f'导入 {len(incoming)} 个方案',self.accept,True));outer.addLayout(row)

    @property
    def replace_existing(self):return bool(self.policy.currentData())

    def refresh_conflicts(self,*_):
        for name,node in self.nodes:
            node.setText(1,('同名，将替换' if self.replace_existing else '同名，另存一份') if name in self.local else '新方案')
