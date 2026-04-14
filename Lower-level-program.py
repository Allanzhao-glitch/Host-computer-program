import serial
import time
import random
import hashlib
import struct
from datetime import datetime

class STM32Simulator:
    def __init__(self, port, baudrate=9600):
        self.ser = serial.Serial(port, baudrate, timeout=1)
        self.led_state = False
        self.led_pwm = 0
        self.adc_value = 2048
        self.button_state = False
        self.buzzer_state = False
        self.relay_state = False
        self.temperature = 25.0
        self.humidity = 60.0
        self.start_time = time.time()
        self.packet_count = 0
        self.version = "v1.2.0"
        self.firmware_hash = hashlib.md5(b"STM32Simulator").hexdigest()[:8].upper()
        
    def run(self):
        print(f"╔══════════════════════════════════════╗")
        print(f"║     STM32 模拟器启动                  ║")
        print(f"║     监听端口: {self.ser.port:<20s}║")
        print(f"║     波特率: {self.ser.baudrate:<21d}║")
        print(f"╚══════════════════════════════════════╝")
        print("等待命令...")
        
        while True:
            if self.ser.in_waiting:
                cmd = self.ser.read(self.ser.in_waiting)
                self.packet_count += 1
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 收到: {cmd.hex(' ').upper()}")
                response = self.process_command(cmd)
                time.sleep(random.uniform(0.002, 0.015))
                self.ser.write(response)
                print(f"发送: {response.hex(' ').upper()}")
            time.sleep(0.01)
            
            if self.packet_count % 50 == 0 and self.packet_count > 0:
                self.update_sensors()
    
    def update_sensors(self):
        self.temperature += random.uniform(-0.5, 0.5)
        self.temperature = max(-40, min(85, self.temperature))
        self.humidity += random.uniform(-2, 2)
        self.humidity = max(0, min(100, self.humidity))
        self.adc_value = int(2048 + random.uniform(-500, 500))
        self.adc_value = max(0, min(4095, self.adc_value))
        if self.led_state:
            self.button_state = random.choice([True, False])
    
    def calc_crc(self, data):
        return sum(data) & 0xFF
    
    def make_response(self, cmd, data=None):
        frame = bytearray([0xAA, cmd])
        if data is not None:
            if isinstance(data, int):
                data = [data]
            frame.append(len(data))
            frame.extend(data)
        else:
            frame.append(0)
        crc = self.calc_crc(frame)
        frame.append(crc)
        return bytes(frame)
    
    def make_error(self, error_code):
        return bytes([0xAA, 0xFF, 0x01, error_code, 
                     self.calc_crc([0xAA, 0xFF, 0x01, error_code])])
    
    def process_command(self, cmd):
        if len(cmd) < 4:
            return self.make_error(0x01)
        
        if cmd[0] != 0xAA:
            return self.make_error(0x02)
        
        received_crc = cmd[-1]
        calculated_crc = self.calc_crc(cmd[:-1])
        if received_crc != calculated_crc:
            print(f"  ⚠ CRC错误: 收到{received_crc:02X}, 计算{calculated_crc:02X}")
            return self.make_error(0x04)
        
        cmd_byte = cmd[1]
        
        if cmd_byte == 0x01:
            return self.cmd_read_led()
        elif cmd_byte == 0x02:
            return self.cmd_set_led(cmd)
        elif cmd_byte == 0x03:
            return self.cmd_read_adc()
        elif cmd_byte == 0x04:
            return self.cmd_set_pwm(cmd)
        elif cmd_byte == 0x05:
            return self.cmd_read_button()
        elif cmd_byte == 0x06:
            return self.cmd_control_buzzer(cmd)
        elif cmd_byte == 0x07:
            return self.cmd_control_relay(cmd)
        elif cmd_byte == 0x08:
            return self.cmd_read_temperature()
        elif cmd_byte == 0x09:
            return self.cmd_read_humidity()
        elif cmd_byte == 0x0A:
            return self.cmd_read_all_sensors()
        elif cmd_byte == 0x10:
            return self.cmd_get_version()
        elif cmd_byte == 0x11:
            return self.cmd_get_system_info()
        elif cmd_byte == 0x12:
            return self.cmd_reset_system()
        elif cmd_byte == 0x20:
            return self.cmd_read_gpio(cmd)
        elif cmd_byte == 0x21:
            return self.cmd_write_gpio(cmd)
        else:
            return self.make_error(0x03)
    
    def cmd_read_led(self):
        data = [1 if self.led_state else 0]
        return self.make_response(0x01, data)
    
    def cmd_set_led(self, cmd):
        if len(cmd) < 5:
            return self.make_error(0x01)
        state = cmd[3]
        self.led_state = bool(state)
        print(f"  → LED状态: {'开启' if self.led_state else '关闭'}")
        return self.make_response(0x02, [1 if self.led_state else 0])
    
    def cmd_read_adc(self):
        print(self.adc_value)
        data = [(self.adc_value >> 8) & 0xFF, self.adc_value & 0xFF]
        return self.make_response(0x03, data)
    
    def cmd_set_pwm(self, cmd):
        if len(cmd) < 5:
            return self.make_error(0x01)
        pwm = cmd[3]
        self.led_pwm = min(100, max(0, pwm))
        self.led_state = self.led_pwm > 0
        print(f"  → PWM占空比: {self.led_pwm}%")
        return self.make_response(0x04, [self.led_pwm])
    
    def cmd_read_button(self):
        self.button_state = random.choice([True, False])
        return self.make_response(0x05, [1 if self.button_state else 0])
    
    def cmd_control_buzzer(self, cmd):
        if len(cmd) < 5:
            return self.make_error(0x01)
        state = cmd[3]
        self.buzzer_state = bool(state)
        print(f"  → 蜂鸣器: {'开启' if self.buzzer_state else '关闭'}")
        return self.make_response(0x06, [1 if self.buzzer_state else 0])
    
    def cmd_control_relay(self, cmd):
        if len(cmd) < 5:
            return self.make_error(0x01)
        state = cmd[3]
        self.relay_state = bool(state)
        print(f"  → 继电器: {'开启' if self.relay_state else '关闭'}")
        return self.make_response(0x07, [1 if self.relay_state else 0])
    
    def cmd_read_temperature(self):
        temp_int = int(self.temperature * 10)
        data = [(temp_int >> 8) & 0xFF, temp_int & 0xFF]
        return self.make_response(0x08, data)
    
    def cmd_read_humidity(self):
        humid_int = int(self.humidity * 10)
        data = [(humid_int >> 8) & 0xFF, humid_int & 0xFF]
        return self.make_response(0x09, data)
    
    def cmd_read_all_sensors(self):
        data = [
            1 if self.led_state else 0,
            self.led_pwm,
            1 if self.button_state else 0,
            1 if self.buzzer_state else 0,
            1 if self.relay_state else 0,
            (self.adc_value >> 8) & 0xFF,
            self.adc_value & 0xFF,
            int(self.temperature * 10) & 0xFF,
            int(self.humidity * 10) & 0xFF,
        ]
        return self.make_response(0x0A, data)
    
    def cmd_get_version(self):
        version_bytes = self.version.encode('ascii')[:16]
        return self.make_response(0x10, list(version_bytes))
    
    def cmd_get_system_info(self):
        uptime = int(time.time() - self.start_time)
        info = [
            (uptime >> 24) & 0xFF,
            (uptime >> 16) & 0xFF,
            (uptime >> 8) & 0xFF,
            uptime & 0xFF,
            (self.packet_count >> 24) & 0xFF,
            (self.packet_count >> 16) & 0xFF,
            (self.packet_count >> 8) & 0xFF,
            self.packet_count & 0xFF,
        ]
        return self.make_response(0x11, info)
    
    def cmd_reset_system(self):
        print("  → 系统复位...")
        self.led_state = False
        self.led_pwm = 0
        self.buzzer_state = False
        self.relay_state = False
        self.start_time = time.time()
        self.packet_count = 0
        return self.make_response(0x12, [0x01])
    
    def cmd_read_gpio(self, cmd):
        if len(cmd) < 5:
            return self.make_error(0x01)
        pin = cmd[3]
        value = random.randint(0, 1)
        return self.make_response(0x20, [pin, value])
    
    def cmd_write_gpio(self, cmd):
        if len(cmd) < 6:
            return self.make_error(0x01)
        pin = cmd[3]
        value = cmd[4]
        print(f"  → GPIO{pin} 设置为: {value}")
        return self.make_response(0x21, [pin, value])

if __name__ == '__main__':
    import sys
    port = sys.argv[1] if len(sys.argv) > 1 else 'COM5'
    baudrate = int(sys.argv[2]) if len(sys.argv) > 2 else 9600
    sim = STM32Simulator(port, baudrate)
    sim.run()