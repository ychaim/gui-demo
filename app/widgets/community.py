from PyQt5.QtWidgets import QWidget
from app.ui.community import Ui_widget_community


class Community(QWidget, Ui_widget_community):
    def __init__(self, parent):
        super().__init__(parent)
        self.setupUi(self)
        self.btn_request_privileges.clicked.connect(lambda: parent.change_stack_index(2))
        self.updater = parent.updater
        self.updater.permissions_changed.connect(self.on_permissions_changed)

    def on_permissions_changed(self, perms):
        self.tabs_community.setTabEnabled(2, 'admin' in perms)

        self.btn_request_privileges.setHidden('admin' in perms and 'mine' in perms)

        self.label_is_guardian.setText('Yes' if 'admin' in perms else 'No')
        self.label_is_validator.setText('Yes' if 'mine' in perms else 'No')
