import requests
from PyQt6.QtCore import QThread, pyqtSignal, QRunnable, QObject
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineUrlRequestInterceptor
from pathlib import Path
from tqdm import tqdm
import time
import socketio
import chardet

class TTSWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, backend, text, service, config):
        super().__init__()
        self.backend = backend
        self.text = text
        self.service = service
        self.config = config
        
    def run(self):
        try:
            response = requests.post(self.backend + '/api/tts', 
                                  json={"text": self.text, "service": self.service, "config": self.config})
            self.finished.emit(response.json())
        except Exception as e:
            self.error.emit(str(e))
        finally:
            # 任务完成后安排线程对象删除
            self.finished.connect(self.deleteLater)
            self.error.connect(self.deleteLater)

# 添加一个信号类
class TTSPoolWorkerSignals(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

class TTSPoolWorker(QRunnable):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, backend, text, service, config):
        super().__init__()
        self.backend = backend
        self.text = text
        self.service = service
        self.config = config
        self.signals = TTSPoolWorkerSignals()
    
    def run(self):
        try:
            response = requests.post(self.backend + '/api/tts', 
                                  json={"text": self.text, "service": self.service, "config": self.config})
            self.signals.finished.emit(response.json())
        except Exception as e:
            self.signals.error.emit(str(e))

class IdentifySpeakerWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(dict)  # 新增进度信号
    
    def __init__(self, backend, base_dir, pre_size, post_size):
        super().__init__()
        self.backend = backend
        self.base_dir = base_dir
        self.pre_size = pre_size
        self.post_size = post_size
        self.sio = socketio.Client(
            reconnection=True,
            reconnection_attempts=3
        )
        self.setup_socket_events()
        
    def setup_socket_events(self):
        @self.sio.on('connect')
        def on_connect():
            print('Connected to server')
            
        @self.sio.on('disconnect')
        def on_disconnect():
            print('Disconnected from server')
            
        @self.sio.on('progress_update')
        def on_progress_update(data):
            print(f"Progress update received: {data}")  # 添加调试输出
            self.progress.emit(data)
            
    def run(self):
        try:
            # 确保WebSocket连接成功
            if not self.sio.connected:
                self.sio.connect(self.backend, 
                               wait_timeout=10,
                               socketio_path='socket.io')
                
            # 等待连接确认
            connection_timeout = 5  # 5秒超时
            start_time = time.time()
            while not self.sio.connected:
                if time.time() - start_time > connection_timeout:
                    raise Exception("WebSocket连接超时")
                self.sleep(0.1)
            
            # 发送API请求
            response = requests.post(self.backend + '/api/identify-speaker', 
                                  json={'base_dir': self.base_dir, 
                                       'pre_size': self.pre_size, 
                                       'post_size': self.post_size})
            
            if response.status_code != 200:
                raise Exception(f"API请求失败: {response.text}")
                
            self.finished.emit(response.json())
            
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if self.sio.connected:
                self.sio.disconnect()
            self.finished.connect(self.deleteLater)
            self.error.connect(self.deleteLater)

class WebSocketTqdm(tqdm):
    """
    通过WebSocket发送进度更新的tqdm子类
    """
    def __init__(self, *args, socketio=None, task_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.socketio = socketio
        self.task_id = task_id
        
    def update(self, n=1):
        super().update(n)
        # 发送进度更新
        if self.socketio:
            # 使用实际存在的format_dict属性
            self.socketio.emit('progress_update', {
                'task_id': self.task_id,
                'percentage': 100 * self.n / self.total if self.total else 0,
                'current': self.n,
                'total': self.total,
                'elapsed': self.format_dict['elapsed'],
                'rate': self.format_dict['rate'] if self.format_dict['rate'] is not None else 0,
                'prefix': self.format_dict['prefix'] if self.format_dict['prefix'] is not None else '',
                'raw_output': self.__str__()
            })

class RequestInterceptor(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        # 打印请求信息
        print(f"请求URL: {info.requestUrl().toString()}")
        print(f"请求方法: {info.requestMethod().data().decode()}")
        print(f"资源类型: {info.resourceType()}")
        print(f"导航类型: {info.navigationType()}")
        print(f"发起者: {info.initiator()}")
        print(f"一方URL: {info.firstPartyUrl().toString()}")
        print("------------------------")
    
def get_text_from_file(input_file: str) -> str:
    def read_text_file(file_path):
        try:
            # 检测文件编码
            with open(file_path, 'rb') as f:
                raw_data = f.read()
                detected = chardet.detect(raw_data)
                encoding = detected['encoding']
            # 使用检测到的编码读取文件
            with open(file_path, 'r', encoding=encoding) as f:
                return f.read()
        except Exception as e:
            print(f"读取{file_path}文件出错: {e}")
            raise e
            
    
    def read_epub_file(file_path):
        book = epub.read_epub(file_path)
        text = ""
        try:
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    soup = BeautifulSoup(item.get_content(), 'html.parser')
                    text += soup.get_text()
            return text
        except Exception as e:
            print(f"读取{file_path}文件出错: {e}")
            raise e
    
    def read_mobi_file(file_path):
        try:
            book = mobi.Mobi(file_path)
            return book.get_text()
        except Exception as e:
            print(f"读取{file_path}文件出错: {e}")
            raise e
        
    # 根据文件扩展名选择读取方式
    file_ext = Path(input_file).suffix.lower()
    if file_ext == '.epub':
        text = read_epub_file(input_file)
    elif file_ext == '.mobi':
        text = read_mobi_file(input_file)
    else:
        text = read_text_file(input_file)
        
    return text