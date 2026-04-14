import serial
import time
import random
import hashlib
from datetime import datetime
from typing import Optional


class STM32Simulator:
    _instance: Optional['STM32Simulator'] = None
    _initialized: bool = False
    
    def __new__(cls, port: str = 'COM5', baudrate: int = 9600):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, port: str = 'COM5', baudrate: int = 9600):
        if STM32Simulator._initialized:
            return
        
        self.ser: Optional[serial.Serial] = None
        self.port = port
        self.baudrate = baudrate
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
        
        STM32Simulator._initialized = True
    
    @classmethod
    def get_instance(cls, port: str = 'COM5', baudrate: int = 9600) -> 'STM32Simulator':
        if cls._instance is None:
            cls._instance = STM32Simulator(port, baudrate)
        return cls._instance
    
    @classmethod
    def reset_instance(cls):
        if cls._instance is not None and cls._instance.ser is not None:
            if cls._instance.ser.is_open:
                cls._instance.ser.close()
        cls._instance = None
        cls._initialized = False
    
    def open(self):
        if self.ser is None or not self.ser.is_open:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
    
    def close(self):
        if self.ser is not None and self.ser.is_open:
            self.ser.close()
    
    def is_connected(self) -> bool:
        return self.ser is not None and self.ser.is_open
    
    def run(self):
        self.open()
        print(f"╔══════════════════════════════════════╗")
        print(f"║     STM32 单例模拟器启动             ║")
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
    
    def calc_crc(self, data: list) -> int:
        return sum(data) & 0xFF
    
    def make_response(self, cmd: int, data=None) -> bytes:
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
    
    def make_error(self, error_code: int) -> bytes:
        return bytes([0xAA, 0xFF, 0x01, error_code, 
                     self.calc_crc([0xAA, 0xFF, 0x01, error_code])])
    
    def process_command(self, cmd: bytes) -> bytes:
        if len(cmd) < 4:
            return self.make_error(0x01)
        
        if cmd[0] != 0xAA:
            return self.make_error(0x02)
        
        received_crc = cmd[-1]
        calculated_crc = self.calc_crc(list(cmd[:-1]))
        if received_crc != calculated_crc:
            print(f"  ⚠ CRC错误: 收到{received_crc:02X}, 计算{calculated_crc:02X}")
            return self.make_error(0x04)
        
        cmd_byte = cmd[1]
        
        command_handlers = {
            0x01: self.cmd_read_led,
            0x02: lambda: self.cmd_set_led(cmd),
            0x03: self.cmd_read_adc,
            0x04: lambda: self.cmd_set_pwm(cmd),
            0x05: self.cmd_read_button,
            0x06: lambda: self.cmd_control_buzzer(cmd),
            0x07: lambda: self.cmd_control_relay(cmd),
            0x08: self.cmd_read_temperature,
            0x09: self.cmd_read_humidity,
            0x0A: self.cmd_read_all_sensors,
            0x10: self.cmd_get_version,
            0x11: self.cmd_get_system_info,
            0x12: self.cmd_reset_system,
            0x20: lambda: self.cmd_read_gpio(cmd),
            0x21: lambda: self.cmd_write_gpio(cmd),
        }
        
        handler = command_handlers.get(cmd_byte)
        if handler:
            return handler()
        return self.make_error(0x03)
    
    def cmd_read_led(self) -> bytes:
        data = [1 if self.led_state else 0]
        return self.make_response(0x01, data)
    
    def cmd_set_led(self, cmd: bytes) -> bytes:
        if len(cmd) < 5:
            return self.make_error(0x01)
        state = cmd[3]
        self.led_state = bool(state)
        print(f"  → LED状态: {'开启' if self.led_state else '关闭'}")
        return self.make_response(0x02, [1 if self.led_state else 0])
    
    def cmd_read_adc(self) -> bytes:
        data = [(self.adc_value >> 8) & 0xFF, self.adc_value & 0xFF]
        return self.make_response(0x03, data)
    
    def cmd_set_pwm(self, cmd: bytes) -> bytes:
        if len(cmd) < 5:
            return self.make_error(0x01)
        pwm = cmd[3]
        self.led_pwm = min(100, max(0, pwm))
        self.led_state = self.led_pwm > 0
        print(f"  → PWM占空比: {self.led_pwm}%")
        return self.make_response(0x04, [self.led_pwm])
    
    def cmd_read_button(self) -> bytes:
        self.button_state = random.choice([True, False])
        return self.make_response(0x05, [1 if self.button_state else 0])
    
    def cmd_control_buzzer(self, cmd: bytes) -> bytes:
        if len(cmd) < 5:
            return self.make_error(0x01)
        state = cmd[3]
        self.buzzer_state = bool(state)
        print(f"  → 蜂鸣器: {'开启' if self.buzzer_state else '关闭'}")
        return self.make_response(0x06, [1 if self.buzzer_state else 0])
    
    def cmd_control_relay(self, cmd: bytes) -> bytes:
        if len(cmd) < 5:
            return self.make_error(0x01)
        state = cmd[3]
        self.relay_state = bool(state)
        print(f"  → 继电器: {'开启' if self.relay_state else '关闭'}")
        return self.make_response(0x07, [1 if self.relay_state else 0])
    
    def cmd_read_temperature(self) -> bytes:
        temp_int = int(self.temperature * 10)
        data = [(temp_int >> 8) & 0xFF, temp_int & 0xFF]
        return self.make_response(0x08, data)
    
    def cmd_read_humidity(self) -> bytes:
        humid_int = int(self.humidity * 10)
        data = [(humid_int >> 8) & 0xFF, humid_int & 0xFF]
        return self.make_response(0x09, data)
    
    def cmd_read_all_sensors(self) -> bytes:
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
    
    def cmd_get_version(self) -> bytes:
        version_bytes = self.version.encode('ascii')[:16]
        return self.make_response(0x10, list(version_bytes))
    
    def cmd_get_system_info(self) -> bytes:
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
    
    def cmd_reset_system(self) -> bytes:
        print("  → 系统复位...")
        self.led_state = False
        self.led_pwm = 0
        self.buzzer_state = False
        self.relay_state = False
        self.start_time = time.time()
        self.packet_count = 0
        return self.make_response(0x12, [0x01])
    
    def cmd_read_gpio(self, cmd: bytes) -> bytes:
        if len(cmd) < 5:
            return self.make_error(0x01)
        pin = cmd[3]
        value = random.randint(0, 1)
        return self.make_response(0x20, [pin, value])
    
    def cmd_write_gpio(self, cmd: bytes) -> bytes:
        if len(cmd) < 6:
            return self.make_error(0x01)
        pin = cmd[3]
        value = cmd[4]
        print(f"  → GPIO{pin} 设置为: {value}")
        return self.make_response(0x21, [pin, value])


def main():
    import sys
    port = sys.argv[1] if len(sys.argv) > 1 else 'COM5'
    baudrate = int(sys.argv[2]) if len(sys.argv) > 2 else 9600
    
    sim = STM32Simulator.get_instance(port, baudrate)
    sim.run()


def test_singleton():
    print("=== 单例模式测试 ===")
    
    sim1 = STM32Simulator.get_instance('COM5', 9600)
    sim2 = STM32Simulator.get_instance('COM6', 115200)
    
    print(f"sim1 端口: {sim1.port}, 波特率: {sim1.baudrate}")
    print(f"sim2 端口: {sim2.port}, 波特率: {sim2.baudrate}")
    print(f"sim1 is sim2: {sim1 is sim2}")
    print(f"端口一致: {sim1.port == sim2.port}")
    print(f"波特率一致: {sim1.baudrate == sim2.baudrate}")
    
    sim1.led_state = True
    print(f"sim1.led_state = True")
    print(f"sim2.led_state = {sim2.led_state}")
    print(f"状态共享: {sim1.led_state == sim2.led_state}")
    
    print("\n=== 测试完成 ===")


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        test_singleton()
    else:
        main()