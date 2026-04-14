import sys
import serial
import serial.tools.list_ports
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QComboBox, QPushButton, 
                             QTextBrowser, QGroupBox, QStatusBar, QMessageBox)
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QFont

class SerialReceiver(QThread):
    data_received = pyqtSignal(bytes)
    
    def __init__(self, serial_port):
        super().__init__()
        self.serial_port = serial_port
        self.running = True
        
    def run(self):
        while self.running:
            if self.serial_port and self.serial_port.is_open:
                if self.serial_port.in_waiting:
                    data = self.serial_port.read(self.serial_port.in_waiting)
                    if data:
                        self.data_received.emit(data)
            self.msleep(10)
    
    def stop(self):
        self.running = False
        self.wait()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.serial_port = None
        self.receiver = None
        self.init_ui()
        self.refresh_ports()
        
    def init_ui(self):
        self.setWindowTitle("STM32 上位机调试工具")
        self.setGeometry(100, 100, 800, 600)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        serial_group = QGroupBox("串口设置")
        serial_layout = QHBoxLayout()
        
        serial_layout.addWidget(QLabel("串口:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(150)
        serial_layout.addWidget(self.port_combo)
        
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        serial_layout.addWidget(self.refresh_btn)
        
        serial_layout.addWidget(QLabel("波特率:"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(['9600', '19200', '38400', '57600', '115200', '230400'])
        self.baud_combo.setCurrentText('9600')
        self.baud_combo.setMinimumWidth(100)
        serial_layout.addWidget(self.baud_combo)
        
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.toggle_connection)
        serial_layout.addWidget(self.connect_btn)
        
        serial_layout.addStretch()
        serial_group.setLayout(serial_layout)
        layout.addWidget(serial_group)
        
        control_group = QGroupBox("控制命令")
        control_layout = QHBoxLayout()
        
        self.read_led_btn = QPushButton("读取LED状态")
        self.read_led_btn.clicked.connect(self.read_led_status)
        self.read_led_btn.setEnabled(False)
        control_layout.addWidget(self.read_led_btn)
        
        self.led_on_btn = QPushButton("LED开")
        self.led_on_btn.clicked.connect(lambda: self.control_led(True))
        self.led_on_btn.setEnabled(False)
        control_layout.addWidget(self.led_on_btn)
        
        self.led_off_btn = QPushButton("LED关")
        self.led_off_btn.clicked.connect(lambda: self.control_led(False))
        self.led_off_btn.setEnabled(False)
        control_layout.addWidget(self.led_off_btn)
        
        self.read_adc_btn = QPushButton("读取ADC")
        self.read_adc_btn.clicked.connect(self.read_adc)
        self.read_adc_btn.setEnabled(False)
        control_layout.addWidget(self.read_adc_btn)
        
        control_layout.addStretch()
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)
        
        status_group = QGroupBox("状态显示")
        status_layout = QVBoxLayout()
        
        self.led_status_label = QLabel("LED状态: 未连接")
        self.led_status_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        status_layout.addWidget(self.led_status_label)
        
        self.adc_label = QLabel("ADC值: --")
        self.adc_label.setStyleSheet("font-size: 14pt;")
        status_layout.addWidget(self.adc_label)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        log_group = QGroupBox("通信日志")
        log_layout = QVBoxLayout()
        self.log_browser = QTextBrowser()
        self.log_browser.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_browser)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("未连接")
        
    def refresh_ports(self):
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(port.device)
        if self.port_combo.count() > 0:
            self.status_bar.showMessage(f"发现 {self.port_combo.count()} 个串口")
    
    def toggle_connection(self):
        if self.serial_port is None or not self.serial_port.is_open:
            self.connect()
        else:
            self.disconnect()
    
    def connect(self):
        port = self.port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "警告", "请选择串口")
            return
            
        try:
            baudrate = int(self.baud_combo.currentText())
            self.serial_port = serial.Serial(port, baudrate, timeout=1)
            
            self.receiver = SerialReceiver(self.serial_port)
            self.receiver.data_received.connect(self.on_data_received)
            self.receiver.start()
            
            self.connect_btn.setText("断开")
            self.port_combo.setEnabled(False)
            self.baud_combo.setEnabled(False)
            self.refresh_btn.setEnabled(False)
            self.read_led_btn.setEnabled(True)
            self.led_on_btn.setEnabled(True)
            self.led_off_btn.setEnabled(True)
            self.read_adc_btn.setEnabled(True)
            
            self.status_bar.showMessage(f"已连接到 {port} @ {baudrate}")
            self.log(f"✓ 连接到 {port} @ {baudrate}")
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"连接失败: {str(e)}")
    
    def disconnect(self):
        if self.receiver:
            self.receiver.stop()
            self.receiver = None
            
        if self.serial_port:
            self.serial_port.close()
            self.serial_port = None
            
        self.connect_btn.setText("连接")
        self.port_combo.setEnabled(True)
        self.baud_combo.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self.read_led_btn.setEnabled(False)
        self.led_on_btn.setEnabled(False)
        self.led_off_btn.setEnabled(False)
        self.read_adc_btn.setEnabled(False)
        
        self.status_bar.showMessage("未连接")
        self.log("✗ 已断开连接")
    
    def send_command(self, cmd_byte, data=None):
        if not self.serial_port or not self.serial_port.is_open:
            QMessageBox.warning(self, "警告", "请先连接串口")
            return
            
        frame = bytearray([0xAA, cmd_byte])
        if data is not None:
            frame.append(len(data))
            frame.extend(data)
        else:
            frame.append(0)
            
        crc = sum(frame) & 0xFF
        frame.append(crc)
        
        self.serial_port.write(frame)
        self.log(f"→ 发送: {frame.hex(' ').upper()}")
    
    def read_led_status(self):
        self.send_command(0x01)
    
    def control_led(self, on):
        self.send_command(0x02, [1 if on else 0])
    
    def read_adc(self):
        self.send_command(0x03)
    
    def on_data_received(self, data):
        self.log(f"← 接收: {data.hex(' ').upper()}")
        self.parse_response(data)
    
    def parse_response(self, data):
        if len(data) < 4:
            self.log("⚠ 数据太短")
            return
            
        if data[0] != 0xAA:
            self.log("⚠ 帧头错误")
            return
            
        cmd = data[1]
        length = data[2]
        
        if cmd == 0x01 and length == 1:
            led_state = "开" if data[3] else "关"
            self.led_status_label.setText(f"LED状态: {led_state}")
            self.log(f"✓ LED状态: {led_state}")
        elif cmd == 0x02 and length == 1:
            led_state = "开" if data[3] else "关"
            self.led_status_label.setText(f"LED状态: {led_state}")
            self.log(f"✓ LED已设置为: {led_state}")
        elif cmd == 0x03 and length == 2:
            adc_value = (data[3] << 8) | data[4]
            self.adc_label.setText(f"ADC值: {adc_value}")
            self.log(f"✓ ADC值: {adc_value}")
        elif cmd == 0xFF:
            self.log(f"⚠ 错误响应: {data[2]}")
    
    def log(self, message):
        self.log_browser.append(message)
        
    def closeEvent(self, event):
        self.disconnect()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())