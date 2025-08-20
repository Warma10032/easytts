from PyQt6.QtWidgets import (QMainWindow, QMessageBox, QFileDialog, 
                             QListWidgetItem, QAbstractItemView, QTableWidgetItem,
                             QMenu, QInputDialog, QLineEdit, QVBoxLayout)
from PyQt6.QtCore import Qt, QUrl, QThreadPool
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineUrlRequestInterceptor, QWebEnginePage
import yaml

from src.ui.Ui_main_window import Ui_MainWindow

from src.sentence_display import SentenceDisplay
from src.speaker_tts_set import SpeakerTTSSet
from src.blocked_progressbar import BlockedProgressBar
from src.utils import *

import json
import os
import re
import zipfile

class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        # 设置UI
        self.setupUi(self)
        
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.book_base_name = ""
        self.cache_text_path = os.path.join(self.project_root, 'cache', 'text')
        self.cache_audio_path = os.path.join(self.project_root, 'cache', 'audio')
        self.cache_identification_path = os.path.join(self.project_root, 'cache', 'speaker_identification')
        self.cache_file_path = None
        
        # 加载配置文件
        self.config_file = os.path.join(self.project_root, 'config.yml')
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        self.load_config()
        
        
        # 添加线程池管理
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(8)  # 限制最大线程数为8
        self.active_workers = []
        
        # 初始化进度条窗口（会自动建立WebSocket连接）
        self.progress_window = BlockedProgressBar(self)
    
        # 连接信号和槽
        self.setup_connections()
        self.setup_page1_connections()
        self.setup_page2_connections()
        self.setup_page3_connections()
        
        # 初始化其他设置
        self.init_ui()
    
    def closeEvent(self, event):
        """重写关闭函数，确保资源正确释放"""
        try:
            # 停止所有正在进行的TTS任务
            for worker in self.active_workers:
                if hasattr(worker, 'signals'):
                    worker.signals.finished.disconnect()
                    worker.signals.error.disconnect()
            
            # 等待线程池完成所有任务
            self.thread_pool.clear()
            self.thread_pool.waitForDone()
            
            # 关闭所有音频播放器
            if hasattr(self, 'audioPlayer'):
                self.audioPlayer.player.stop()
            if hasattr(self, 'audioPlayer2'):
                self.audioPlayer2.player.stop()
                
            # 清理所有句子显示组件
            self.clear_sentence_displays()
            
            # 尝试关闭后端服务
            try:
                requests.post(self.backend + '/api/shutdown')
            except:
                pass
                
            # 接受关闭事件
            event.accept()
            
        except Exception as e:
            print(f"关闭时出错：{str(e)}")
            event.accept()  # 即使出错也关闭窗口
            
    def init_ui(self):
        self.audioPlayer.beforeButton.hide()
        self.audioPlayer.nextButton.hide()
        self.audioPlayer2.beforeButton.hide()
        self.audioPlayer2.nextButton.hide()
        self.ttsSet.saveSetButton.hide()
        
    def setup_connections(self):
        # 页面切换按钮
        self.pageButton1.clicked.connect(lambda: self.pageStackedWidget.setCurrentIndex(0))
        self.pageButton2.clicked.connect(lambda: self.pageStackedWidget.setCurrentIndex(1))
        self.pageButton3.clicked.connect(lambda: self.pageStackedWidget.setCurrentIndex(2))
        
    '''------ Page1 ------'''
    def setup_page1_connections(self):
        # 生成按钮
        self.ttsSet.generateButton.clicked.connect(self.on_generate_clicked)
        
    def on_generate_clicked(self):
        if hasattr(self, 'worker') and self.worker.isRunning():
            QMessageBox.warning(self, "警告", "已有正在进行的TTS任务，请等待完成")
            return
        
        text = self.ttsTextEdit.toPlainText()
        service = self.ttsSet.ttsProviderComboBox.currentText()
        voice_name = self.ttsSet.edgeTTSVoiceSet.currentText()
        # 使用映射获取正确的voice id
        voice_id = self.ttsSet.voice_mapping[voice_name]
        config = {"voice": voice_id}
        # 创建工作线程
        self.worker = TTSWorker(self.backend, text, service, config)
        self.worker.finished.connect(self._handle_tts_result)
        self.worker.error.connect(self._handle_tts_error)
        self.worker.start()
        
    def _handle_tts_result(self, result):
        if result['success']:
            # 获取音频URL
            audio_url = result['audio_url']
            # 使用 AudioPlayer 类的加载音频方法
            self.audioPlayer.load_audio(audio_url)
            self.audioPlayer.play_pause()  # 开始播放
        else:
            print(f"生成失败：{result['error']}")
            
    def _handle_tts_error(self, error):
        print(f"生成错误：{error}")
        
    '''------ Page2 ------'''
    def setup_page2_connections(self):
        # 文件选择按钮
        self.fileOpenButton.clicked.connect(self.open_file)
        # 文件保存按钮
        self.fileSaveButton.clicked.connect(self.save_file)
        # 字体选择combebox
        self.fontComboBox.currentFontChanged.connect(self.on_font_changed)
        # 字体大小spinbox
        self.fontSizeSpinBox.valueChanged.connect(self.on_font_size_changed)
        # 文本替换按钮
        self.replaceButton.clicked.connect(self.replace_text)
        # 分句按钮
        self.splitButton.clicked.connect(self.split_sentences)
        # 说话人识别按钮
        self.speakerIdentificationButton.clicked.connect(self.identify_speaker)
        # 展示tableWidget让用户调整说话人
        self.normalizeBeginButton.clicked.connect(self.update_speakers_list)
        self.editTableWidget.horizontalHeader().sectionDoubleClicked.connect(self.edit_header)
        self.editTableWidget.customContextMenuRequested.connect(self.show_table_context_menu)
        # 根据tableWidget对说话人进行调整
        self.normalizeEndButton.clicked.connect(self.normalize_speaker)
        # 说话人识别结果保存按钮
        self.identificationSaveButton.clicked.connect(self.save_identification_result)
        # 说话人TTS设置开始按钮
        self.speakerTTSSetBeginButton.clicked.connect(self.set_speaker)
        # 所有TTS生成按钮
        self.totalGenerateButton.clicked.connect(self.total_generate_tts)
        # 所有音频打包下载按钮
        self.totalSaveButton.clicked.connect(self.save_total_audio)

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择文件", "", "文本文件(*.txt *.epub *.mobi);;所有文件 (*.*)")
        if file_path:
            try:
                self.book_base_name = os.path.splitext(os.path.basename(file_path))[0]
                file_ext = os.path.splitext(file_path)[1]
                text = get_text_from_file(file_path)
                self.fileTextEdit.setPlainText(text)
                # 在cache/text中保存文件，文件名不改
                self.cache_file_path = os.path.join(self.cache_text_path, self.book_base_name + file_ext)
                with open(self.cache_file_path, 'w', encoding='utf-8') as f:
                    f.write(text)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"打开文件时出错: {str(e)}")
          
    def save_file(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "保存文件", "", "文本文件 (*.txt);;所有文件 (*.*)")
        if file_path:
            text = self.fileTextEdit.toPlainText()
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(text)
                # 显示保存成功提示
                self.cache_file_path = file_path
                QMessageBox.information(self, "保存成功", f"文件已保存至: {file_path}")
            except Exception as e:
                # 显示保存失败提示
                QMessageBox.critical(self, "保存失败", f"保存文件时出错: {str(e)}")
                
    def on_font_changed(self, font):
        self.fileTextEdit.setFont(font)

    def on_font_size_changed(self, size):
        font = self.fileTextEdit.font()
        font.setPointSize(size)
        self.fileTextEdit.setFont(font)
        
    def replace_text(self):
        old_text = self.replaceEdit1.text()
        new_text = self.replaceEdit2.text()
        
        if not old_text:  # 如果查找文本为空，直接返回
            return
        
        # 获取当前文本编辑器中的文本
        current_text = self.fileTextEdit.toPlainText()
        
        # 检查是否是正则表达式格式：re(...)
        if old_text.startswith('re(') and old_text.endswith(')'):
            # 提取正则表达式内容
            pattern_text = old_text[3:-1]  # 去掉 re( 和 )
            try:
                # 编译正则表达式
                pattern = re.compile(pattern_text)
                # 使用正则表达式替换
                result_text = pattern.sub(new_text, current_text)
                is_regex = True
            except re.error:
                # 正则表达式编译失败，作为普通文本处理
                result_text = current_text.replace(old_text, new_text)
                is_regex = False
        else:
            # 普通文本替换
            result_text = current_text.replace(old_text, new_text)
            is_regex = False
        
        # 更新文本编辑器内容
        self.fileTextEdit.setPlainText(result_text)
        
        # 显示替换结果提示
        count = len(re.findall(pattern_text, current_text)) if is_regex else current_text.count(old_text)
        QMessageBox.information(
            self,
            "替换完成",
            f"使用{'正则表达式' if is_regex else '普通文本'}替换\n共替换了 {count} 处文本"
        )
        
    def split_sentences(self):
        """分割文本为句子并为每个句子创建显示组件"""
        if not self.cache_file_path:
            '''TODO: 仅有文字时也要可以进行，在这里最好自动保存一下文件，以免用户修改而我们获取的还是路径下的文件 '''
            QMessageBox.warning(self, "警告", "请先打开文件")
            return
            
        text = self.fileTextEdit.toPlainText()
        with open(self.cache_file_path, 'w', encoding='utf-8') as f:
            f.write(text)
        
        try:
            # 访问api/split-sentences
            response = requests.post(self.backend +'/api/split-sentences', json={'text_dir': self.cache_file_path, 'split_rule': self.splitRuleComboBox.currentText()})
            
            if not response.ok:
                QMessageBox.critical(self, "错误", f"服务器响应错误: {response.status_code}")
                return
                
            data = response.json()
            if data['success']:
                cache_sentences_path = data['sentences_dir']
                
                # 清除现有的句子显示组件
                self.clear_sentence_displays()
                
                # 从JSON文件读取句子
                try:
                    with open(cache_sentences_path, 'r', encoding='utf-8') as f:
                        sentences_data = json.load(f)
                        sentences = sentences_data['sentences']
                        quotes_idx = sentences_data['quotes_idx']
                    
                    # 为每个句子创建显示组件
                    for sentence in sentences:
                        self.add_sentence_display(sentence[0], sentence[3])
                        
                    QMessageBox.information(self, "分句完成", f"成功分割为 {len(sentences)} 个句子")
                    
                except Exception as e:
                    QMessageBox.critical(self, "错误", f"读取句子数据失败: {str(e)}")
            else:
                QMessageBox.critical(self, "错误", f"分句失败: {data.get('error', '未知错误')}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"分句请求失败: {str(e)}")

    def clear_sentence_displays(self):
        """清除所有句子显示组件"""
        while self.sentenceDisplayLayout.count():
            item = self.sentenceDisplayLayout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def add_sentence_display(self, sentence_text, sentence_idx):
        """添加一个句子显示组件到布局中"""
        
        # 创建句子显示组件
        sentence_widget = SentenceDisplay(
            sentence_text=sentence_text,
            sentence_index=sentence_idx,
        )
        
        self.sentenceDisplayLayout.addWidget(sentence_widget)

    def identify_speaker(self):
        if not self.cache_file_path:
            QMessageBox.warning(self, "警告", "请先打开文件")
            return

        if not os.path.exists(os.path.join(self.project_root, 'cache', 'text', self.book_base_name + '_sentences.json')):
            QMessageBox.warning(self, "警告", "请先进行分句")
            return
        
        if hasattr(self, 'worker') and self.worker.isRunning():
            QMessageBox.warning(self, "警告", "已有正在进行的TTS任务，请等待完成")
            return

        # 创建并启动工作线程
        self.worker = IdentifySpeakerWorker(self.backend,
                                        self.book_base_name, 
                                        self.preContextSpinBox.value(),
                                        self.postContextSpinBox.value())
        self.worker.finished.connect(self._handle_identify_speaker_result)
        self.worker.error.connect(self._handle_identify_speaker_error)
        self.worker.progress.connect(self.progress_window.update_progress) 
        self.worker.start()
        
        self.progress_window.show()
        
    def _handle_identify_speaker_result(self, data):
        if data['success']:
            self.cache_speakers_path = data['speakers_dir']
            self.cache_nbest_path = data['nbest_dir']
            self.progress_window.hide()
            # 读取并更新句子显示组件的说话人信息
            try:
                with open(self.cache_speakers_path, 'r', encoding='utf-8') as f:
                    speakers_data = json.load(f)

                # 遍历所有说话人预测结果
                for sentence_id, speaker_name in speakers_data.items():
                    # 从 "sentence_X" 中提取索引数字
                    sentence_index = int(sentence_id.split('_')[1])

                    # 找到对应的句子显示组件并更新说话人信息
                    for i in range(self.sentenceDisplayLayout.count()):
                        sentence_widget = self.sentenceDisplayLayout.itemAt(i).widget()
                        if sentence_widget and sentence_widget.sentence_index == sentence_index:
                            sentence_widget.speakerLabel.setText(speaker_name)
                            break
                
                # 更新说话人列表
                self.update_speakers_list()
                    
                QMessageBox.information(self, "说话人识别完成", f"成功识别 {len(speakers_data)} 个说话人")

            except Exception as e:
                QMessageBox.critical(self, "错误", f"读取说话人识别数据失败: {str(e)}")
        else:
            self.progress_window.hide()  # 出错时关闭进度条窗口
            QMessageBox.critical(self, "错误", f"说话人识别失败: {data.get('error', '未知错误')}")

    def _handle_identify_speaker_error(self, error_msg):
        self.progress_window.hide()  # 出错时关闭进度条窗口
        QMessageBox.critical(self, "错误", f"说话人识别请求失败: {error_msg}")
    
    def update_speakers_set(self):
        """从所有sentenceDisplay组件中获取说话人集合"""
        self.speakers_set = set()
        for i in range(self.sentenceDisplayLayout.count()):
            sentence_widget = self.sentenceDisplayLayout.itemAt(i).widget()
            if sentence_widget and sentence_widget.speakerLabel.text():
                self.speakers_set.add(sentence_widget.speakerLabel.text())
        
    def update_speakers_list(self):
        """更新说话人列表显示"""
        # 在showListWidget中显示所有说话人（按长度排序）
        self.showListWidget.clear()
        self.editTableWidget.clear()
        self.update_speakers_set()
        sorted_speakers = sorted(self.speakers_set, key=len)
        for speaker in sorted_speakers:
            item = QListWidgetItem(speaker)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)  # 允许拖动
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)    # 禁止编辑
            self.showListWidget.addItem(item)
        
        # 设置showListWidget的拖放属性
        self.showListWidget.setDragEnabled(True)
        self.showListWidget.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.showListWidget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        
        # 设置editTableWidget的拖放属性
        self.editTableWidget.setAcceptDrops(True)
        self.editTableWidget.setDragEnabled(True) 
        self.editTableWidget.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)  # 同时支持内部移动和外部拖入
        self.editTableWidget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        
        # 初始化表格
        self.editTableWidget.setRowCount(3)
        self.editTableWidget.setColumnCount(3)
        
        # 设置初始表头
        for i in range(3):
            header_item = QTableWidgetItem(f'角色{i+1}')
            header_item.setData(Qt.ItemDataRole.UserRole, False)  # 添加自定义属性表示表头是否修改过
            self.editTableWidget.setHorizontalHeaderItem(i, header_item)
        
        # 设置列表头可编辑
        self.editTableWidget.horizontalHeader().setSectionsClickable(True)
        # 设置表格的上下文菜单策略
        self.editTableWidget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # 连接拖放完成信号
        self.editTableWidget.dropEvent = self.handle_drop
        
    def edit_header(self, logical_index):
        """编辑表头"""
        header_item = self.editTableWidget.horizontalHeaderItem(logical_index)
        current_text = header_item.text() if header_item else f'角色{logical_index + 1}'
        
        text, ok = QInputDialog.getText(self, "编辑角色名", "请输入新的角色名:", 
                                      QLineEdit.EchoMode.Normal, current_text)
        if ok and text:
            item = QTableWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, True)  # 标记为已修改
            self.editTableWidget.setHorizontalHeaderItem(logical_index, item)
            
    def show_table_context_menu(self, pos):
        """显示表格的右键菜单"""
        menu = QMenu(self)
        
        # 添加行列操作
        add_row_action = menu.addAction("添加行")
        add_col_action = menu.addAction("添加列")
        menu.addSeparator()
        del_row_action = menu.addAction("删除行")
        del_col_action = menu.addAction("删除列")
        
        # 显示菜单
        action = menu.exec(self.editTableWidget.mapToGlobal(pos))
        
        if action == add_row_action:
            current_rows = self.editTableWidget.rowCount()
            self.editTableWidget.setRowCount(current_rows + 1)
        elif action == add_col_action:
            current_cols = self.editTableWidget.columnCount()
            self.editTableWidget.setColumnCount(current_cols + 1)
            new_header = QTableWidgetItem(f'角色{current_cols + 1}')
            new_header.setData(Qt.ItemDataRole.UserRole, False)
            self.editTableWidget.setHorizontalHeaderItem(current_cols, new_header)
        elif action == del_row_action:
            current_row = self.editTableWidget.currentRow()
            if current_row >= 0:
                # 获取该行所有单元格的文本
                for col in range(self.editTableWidget.columnCount()):
                    item = self.editTableWidget.item(current_row, col)
                    if item and item.text():
                        # 将文本添加回showListWidget
                        self.showListWidget.addItem(QListWidgetItem(item.text()))
                self.editTableWidget.removeRow(current_row)
        elif action == del_col_action:
            current_col = self.editTableWidget.currentColumn()
            if current_col >= 0:
                # 获取该列所有单元格的文本
                for row in range(self.editTableWidget.rowCount()):
                    item = self.editTableWidget.item(row, current_col)
                    if item and item.text():
                        # 将文本添加回showListWidget
                        self.showListWidget.addItem(QListWidgetItem(item.text()))
                self.editTableWidget.removeColumn(current_col)
        
    def handle_drop(self, event):
        """处理拖放事件"""
        # 获取拖放的目标位置
        pos = event.position()
        row = self.editTableWidget.rowAt(int(pos.y()))
        col = self.editTableWidget.columnAt(int(pos.x()))
        
        # 如果有有效的列
        if col >= 0:
            # 根据拖放源获取选中项
            if event.source() == self.showListWidget:
                items = self.showListWidget.selectedItems()
                is_from_list = True
            elif event.source() == self.editTableWidget:
                items = self.editTableWidget.selectedItems()
                is_from_list = False
            else:
                event.ignore()
                return
                
            if not items:
                event.ignore()
                return
                
            # 获取当前表头项
            header_item = self.editTableWidget.horizontalHeaderItem(col)
            # 检查表头是否未被修改过
            if not header_item.data(Qt.ItemDataRole.UserRole):
                # 使用第一个拖入的角色名更新表头
                new_header = QTableWidgetItem(items[0].text())
                new_header.setData(Qt.ItemDataRole.UserRole, True)
                self.editTableWidget.setHorizontalHeaderItem(col, new_header)
            
            # 处理所有选中项
            for item in items:
                # 查找或创建目标行
                target_row = self._find_or_create_target_row(row, col)
                
                # 创建表格项
                table_item = QTableWidgetItem(item.text())
                table_item.setFlags(table_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.editTableWidget.setItem(target_row, col, table_item)
                
                # 如果是从列表拖入，从源列表中删除
                if is_from_list:
                    self.showListWidget.takeItem(self.showListWidget.row(item))
                # 如果是表格内部移动，删除原位置的项
                else:
                    self.editTableWidget.takeItem(item.row(), item.column())
            
            event.accept()
        else:
            event.ignore()
    
    def _find_or_create_target_row(self, row, col):
        """查找或创建目标行"""
        if row >= 0 and self.editTableWidget.item(row, col) is None:
            return row
        else:
            # 从第一行开始查找空位
            for r in range(self.editTableWidget.rowCount()):
                if not self.editTableWidget.item(r, col) or not self.editTableWidget.item(r, col).text():
                    return r
            # 如果没有找到空位，则添加新行
            current_rows = self.editTableWidget.rowCount()
            self.editTableWidget.setRowCount(current_rows + 1)
            return current_rows
        
    def normalize_speaker(self):
        """归一化说话人列表"""
        # 检查是否所有说话人都已分配角色
        if self.showListWidget.count() > 0:
            QMessageBox.warning(self, "警告", "请先将所有说话人分配到对应角色")
            return

        # 检查表格是否有空列
        for col in range(self.editTableWidget.columnCount()):
            if not self.editTableWidget.horizontalHeaderItem(col):
                QMessageBox.warning(self, "警告", "请删除所有空列")
                return
        
        # 构建替换映射表
        speaker_mapping = {}
        for col in range(self.editTableWidget.columnCount()):
            # 获取列表头（目标角色名）
            header_item = self.editTableWidget.horizontalHeaderItem(col)
            if not header_item:
                continue
            target_speaker = header_item.text()
            
            # 获取该列所有单元格的文本（源说话人名）
            for row in range(self.editTableWidget.rowCount()):
                item = self.editTableWidget.item(row, col)
                if item and item.text():
                    speaker_mapping[item.text()] = target_speaker
        
        # 如果没有映射关系，直接返回
        if not speaker_mapping:
            QMessageBox.warning(self, "警告", "请先在表格中设置角色映射关系")
            return
            
        # 遍历所有句子显示组件，进行说话人替换
        replace_count = 0
        for i in range(self.sentenceDisplayLayout.count()):
            sentence_widget = self.sentenceDisplayLayout.itemAt(i).widget()
            if sentence_widget:
                current_speaker = sentence_widget.speakerLabel.text()
                if current_speaker in speaker_mapping:
                    sentence_widget.speakerLabel.setText(speaker_mapping[current_speaker])
                    replace_count += 1
        
        # 显示替换结果
        QMessageBox.information(self, "归一化完成", f"共替换了 {replace_count} 处说话人标签")
        
    def save_identification_result(self):
        """保存识别说话人识别结果"""
        # 构建新的说话人结果
        updated_predictions = {}
        for i in range(self.sentenceDisplayLayout.count()):
            item = self.sentenceDisplayLayout.itemAt(i)
            widget = item.widget()
            if widget:
                # 从 "sentence_X" 标签中提取索引
                sentence_id = f"sentence_{widget.sentence_index}"
                speaker_name = widget.speakerLabel.text()
                updated_predictions[sentence_id] = speaker_name
        
        # 确保目标目录存在
        save_dir = os.path.join(self.cache_identification_path, self.book_base_name)
        os.makedirs(save_dir, exist_ok=True)
        
        # 保存更新后的预测结果
        save_path = os.path.join(save_dir, 'predictions_update.json')
        try:
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(updated_predictions, f, ensure_ascii=False, indent=4)
            QMessageBox.information(self, "保存成功", f"已保存更新后的说话人识别结果到：\n{save_path}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存说话人识别结果时出错：{str(e)}")
        
    def set_speaker(self):
        """设置说话人TTS配置"""
        # 先清除现有的配置组件
        while self.speakerSetLayout.count():
            item = self.speakerSetLayout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
                
        # 更新说话人集合
        self.update_speakers_set()
        
        # 在speakerSetLayout中添加SpeakerTTSSet组件
        for speaker_name in self.speakers_set:
            speaker_tts_set = SpeakerTTSSet(speaker_name=speaker_name)
            self.speakerSetLayout.addWidget(speaker_tts_set)
            
    def total_generate_tts(self):
        """批量生成TTS音频"""
        # 获取所有说话人的TTS设置
        speaker_settings = {}
        for i in range(self.speakerSetLayout.count()):
            speaker_widget = self.speakerSetLayout.itemAt(i).widget()
            if speaker_widget:
                speaker_name = speaker_widget.speaker_name
                service = speaker_widget.service
                config = speaker_widget.config
                speaker_settings[speaker_name] = {
                    "service": service,
                    "config": config
                }
                
        # 检查是否有说话人没有设置TTS设置
        self.update_speakers_set
        for speaker_name in self.speakers_set:
            if speaker_name not in speaker_settings:
                QMessageBox.warning(self, "警告", f"未找到说话人 {speaker_name} 的TTS设置")
                return
                
        # 遍历所有句子进行TTS生成
        total_tasks = self.sentenceDisplayLayout.count()
        self.completed_tasks = 0
        for i in range(total_tasks):
            sentence_widget = self.sentenceDisplayLayout.itemAt(i).widget()
            if sentence_widget:
                # 获取句子文本和说话人
                text = sentence_widget.sentence_text
                speaker = sentence_widget.speakerLabel.text()
                
                # 获取TTS设置
                settings = speaker_settings[speaker]
               
                # 创建线程池工作线程
                worker = TTSPoolWorker(self.backend ,text, settings["service"], settings["config"])
                # 连接信号
                worker.signals.finished.connect(
                    lambda result, w=sentence_widget: self._handle_total_tts_result(result, w, total_tasks))
                worker.signals.error.connect(
                    lambda error, w=sentence_widget: self._handle_total_tts_error(error, w, total_tasks))
                # 添加到线程池
                self.active_workers.append(worker)
                self.thread_pool.start(worker)
                
    def _handle_total_tts_result(self, result, sentence_widget, total_tasks):
        """处理批量TTS生成结果"""
        if result['success']:
            # 获取音频URL并加载到对应的AudioPlayer
            audio_url = result['audio_url']
            sentence_widget.sentencePlyer.load_audio(audio_url)
        else:
            QMessageBox.warning(self, "生成失败", 
                              f"句子 {sentence_widget.sentence_index} 生成失败：{result.get('error', '未知错误')}")
        # 增加完成计数并检查是否所有任务都完成
        self.completed_tasks += 1
        if self.completed_tasks == total_tasks:
            self.merge_all_audio()
         
    def _handle_total_tts_error(self, error, sentence_widget, total_tasks):
        """处理批量TTS生成错误"""
        QMessageBox.critical(self, "生成错误", 
                           f"句子 {sentence_widget.sentence_index} 生成错误：{error}")
                # 增加完成计数并检查是否所有任务都完成
        self.completed_tasks += 1
        if self.completed_tasks == total_tasks:
            self.merge_all_audio()
    
    def merge_all_audio(self):
        """合并所有生成的音频"""
        # 收集所有有效的音频路径
        audio_paths = []
        for i in range(self.sentenceDisplayLayout.count()):
            sentence_widget = self.sentenceDisplayLayout.itemAt(i).widget()
            if sentence_widget and sentence_widget.sentencePlyer.audio_path:
                audio_paths.append(sentence_widget.sentencePlyer.audio_path)
        
        if not audio_paths:
            QMessageBox.warning(self, "警告", "没有找到可合并的音频文件")
            return
            
        try:
            # 创建合并后的音频文件路径
            merged_filename = f"{self.book_base_name}_audio.mp3"
            output_path = os.path.join(self.cache_audio_path, merged_filename)
            
            # 创建包含所有音频文件路径的临时文件
            temp_list_path = os.path.join(self.cache_audio_path, "temp_list.txt")
            with open(temp_list_path, 'w', encoding='utf-8') as f:
                for audio_path in audio_paths:
                    f.write(f"file '{audio_path}'\n")
            
            # 使用ffmpeg合并音频
            import subprocess
            cmd = [
                'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                '-i', temp_list_path, '-c', 'copy', output_path
            ]
            subprocess.run(cmd, check=True)
            
            # 删除临时文件
            os.remove(temp_list_path)
            
            # 加载到audioPlayer2
            self.audioPlayer2.load_audio(output_path)
            
            QMessageBox.information(self, "合并完成", f"已将 {len(audio_paths)} 个音频文件合并为：\n{output_path}")
            
        except subprocess.CalledProcessError as e:
            QMessageBox.critical(self, "合并失败", f"音频合并失败：ffmpeg 错误")
        except Exception as e:
            QMessageBox.critical(self, "合并失败", f"音频合并失败：{str(e)}")        

    def save_total_audio(self):
        """保存所有音频"""
        # 收集所有有效的音频路径
        audio_files = []
        for i in range(self.sentenceDisplayLayout.count()):
            sentence_widget = self.sentenceDisplayLayout.itemAt(i).widget()
            if sentence_widget and sentence_widget.sentencePlyer.audio_path:
                audio_files.append({
                    'path': sentence_widget.sentencePlyer.audio_path,
                    'index': sentence_widget.sentence_index
                })
        
        # 如果没有音频文件，显示提示并返回
        if not audio_files:
            QMessageBox.warning(self, "警告", "没有找到可保存的音频文件")
            return
            
        # 让用户选择保存路径
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存音频文件",
            f"{self.book_base_name}_audio.zip" if self.book_base_name else "audio.zip",
            "ZIP文件 (*.zip)"
        )
        
        if not save_path:
            return
            
        try:
            # 创建zip文件
            with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 添加所有音频文件，使用原始index命名
                for file_info in audio_files:
                    # 获取原始文件的扩展名
                    ext = os.path.splitext(file_info['path'])[1]
                    # 直接使用index作为文件名（4位数字格式）
                    new_name = f"{int(file_info['index']):04d}{ext}"
                    # 添加到zip文件
                    zipf.write(file_info['path'], new_name)
            
            QMessageBox.information(self, "保存成功", f"已将 {len(audio_files)} 个音频文件保存至：\n{save_path}")
            
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存音频文件时出错：{str(e)}")
            
    '''------ Page3 ------'''
    def setup_page3_connections(self):
        # 创建自定义配置文件
        self.profile = QWebEngineProfile("my_profile")
        # 创建并设置请求拦截器
        self.interceptor = RequestInterceptor()
        self.profile.setUrlRequestInterceptor(self.interceptor)
        
        # 创建 WebEngineView 并使用自定义配置文件
        self.web_view = QWebEngineView()
        page = QWebEnginePage(self.profile, self.web_view)
        self.web_view.setPage(page)
        
        # 将 web_view 添加到 widget 的布局中
        layout = QVBoxLayout(self.webWidget)
        layout.addWidget(self.web_view)
        
        # 连接按钮事件
        self.webUrlConnectButton.clicked.connect(self.connect_web_url)
        
        # 连接设置变更事件
        self.setSaveButton.clicked.connect(self.save_config)
        
        
    def load_config(self):
        """加载配置文件"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
                if self.config:
                    self.backend = self.config.get('backend_url', 'http://localhost:10032').rstrip('/')
                    self.threadsNumber = self.config.get('tts_threads', 1)
                    self.backendUrl.setText(self.backend)
                    self.spinBox.setValue(self.threadsNumber)
        except Exception as e:
            QMessageBox.warning(self, "警告", f"加载配置文件失败：{str(e)}")
            
    def save_config(self):
        """保存配置到文件"""
        try:
            config = {
                'backend_url': self.backendUrl.text(),
                'tts_threads': self.spinBox.value()
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.safe_dump(config, f, allow_unicode=True)
        except Exception as e:
            QMessageBox.warning(self, "警告", f"保存配置文件失败：{str(e)}")
            
    def connect_web_url(self):
        """连接到Web URL"""
        try:
            url = self.webUrl.text()
            if not url.startswith(('http://', 'https://')):
                url = 'http://' + url
            self.web_view.load(QUrl(url))
        except Exception as e:
            QMessageBox.warning(self, "警告", f"连接失败：{str(e)}")
    