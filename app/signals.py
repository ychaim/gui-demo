# -*- coding: utf-8 -*-
"""QT Signals that the application provides"""
from PyQt5.QtCore import QObject, pyqtSignal, QProcess


class Signals(QObject):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('sync')

    # Blockchain node status
    node_started = pyqtSignal()
    node_finished = pyqtSignal(int, QProcess.ExitStatus)
    node_error = pyqtSignal(QProcess.ProcessError)

    # simple rpc method syncs
    getinfo = pyqtSignal(object)
    getblockchaininfo = pyqtSignal(object)
    getruntimeparams = pyqtSignal(object)

    # database rpc syncs
    listwallettransactions = pyqtSignal()
    listpermissions = pyqtSignal()
    liststreamitems_alias = pyqtSignal()
    listblocks = pyqtSignal()

    votes_changed = pyqtSignal()

    # custom signals

    #: profile changed
    profile_changed = pyqtSignal(object)

    block_sync_changed = pyqtSignal(dict)
    transactions_changed = pyqtSignal(list)

    is_admin_changed = pyqtSignal(bool)
    is_miner_changed = pyqtSignal(bool)


signals = Signals()