import sys
from PyQt6.QtWidgets import QApplication
from src.main_window import MainWindow
import src.ui.resource.res_rc
from src.client.client_factory import ClientFactory

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()