import serial
import asyncio
import random
import hashlib
from datetime import datetime
from typing import Optional, Dict, List, Callable
import json


class STM32Simulator:
    _instance: Optional['STM32Simulator'] = None
    
    def __new__(cls, port: str = 'COM5', baudrate: int = 9600):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, port: str = 'COM5', baudrate: int = 9600):
        if self._initialized:
            return
        
        self.port = port
        self.baudrate = baudrate
        self.ser: Optional[serial.Serial] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.running = False
        
        self.led_state = False
        self.led_pwm = 0
        self.adc_value = 2048
        self.button_state = False
        self.buzzer_state = False
        self.relay_state = False
        self.temperature = 25.0
        self.humidity = 60.0
        self.start_time = asyncio.get_event_loop().time()
        self.packet_count = 0
        self.version = "v1.2.0"
        
        self._initialized = True
        self._observers: List[Callable] = []
    
    @classmethod
    def get_instance(cls, port: str = 'COM5', baudrate: int = 9600) -> 'STM32Simulator':
        return cls(port, baudrate)
    
    @classmethod
    def reset_instance(cls):
        if cls._instance is not None:
            cls._instance = None
    
    def add_observer(self, callback: Callable):
        self._observers.append(callback)
    
    def remove_observer(self, callback: Callable):
        if callback in self._observers:
            self._observers.remove(callback)
    
    def _notify(self, event: str, data: Dict):
        for observer in self._observers:
            try:
                observer(event, data)
            except Exception as e:
                print(f"通知观察者失败: {e}")
    
    async def open(self):
        if self.ser is None or not self.ser.is_open:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
            self.reader = asyncio.StreamReader()
            self.reader.set_transport(self.ser)
    
    async def close(self):
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        if self.ser and self.ser.is_open:
            self.ser.close()
    
    async def start(self):
        if self.running:
            print("模拟器已在运行")
            return
        
        await self.open()
        self.running = True
        self.loop = asyncio.get_event_loop()
        
        asyncio.create_task(self._serial_reader())
        asyncio.create_task(self._sensor_updater())
        
        print(f"[协程] STM32模拟器启动，监听 {self.port} @ {self.baudrate}")
    
    async def stop(self):
        self.running = False
        await self.close()
        print("[协程] 模拟器已停止")
    
    async def _serial_reader(self):
        print("[串口读取协程] 开始运行")
        
        while self.running:
            try:
                if self.ser and self.ser.is_open and self.ser.in_waiting:
                    data = self.ser.read(self.ser.in_waiting)
                    if data:
                        await self._handle_received(data)
                await asyncio.sleep(0.01)
            except Exception as e:
                print(f"读取错误: {e}")
                await asyncio.sleep(0.1)
        
        print("[串口读取协程] 结束")
    
    async def _handle_received(self, cmd: bytes):
        self.packet_count += 1
        print(f"[协程] 收到: {cmd.hex(' ').upper()}")
        
        response = self._process_command(cmd)
        
        await asyncio.sleep(random.uniform(0.002, 0.015))
        
        if self.ser and self.ser.is_open:
            self.ser.write(response)
            print(f"[协程] 发送: {response.hex(' ').upper()}")
    
    async def _sensor_updater(self):
        print("[传感器更新协程] 开始运行")
        
        while self.running:
            await asyncio.sleep(2)
            
            self.temperature += random.uniform(-0.5, 0.5)
            self.temperature = max(-40, min(85, self.temperature))
            self.humidity += random.uniform(-2, 2)
            self.humidity = max(0, min(100, self.humidity))
            self.adc_value = int(2048 + random.uniform(-500, 500))
            self.adc_value = max(0, min(4095, self.adc_value))
            
            self._notify('sensors_updated', {
                'temperature': self.temperature,
                'humidity': self.humidity,
                'adc_value': self.adc_value,
            })
    
    def _calc_crc(self, data: list) -> int:
        return sum(data) & 0xFF
    
    def _make_response(self, cmd: int, data=None) -> bytes:
        frame = bytearray([0xAA, cmd])
        if data is not None:
            if isinstance(data, int):
                data = [data]
            frame.append(len(data))
            frame.extend(data)
        else:
            frame.append(0)
        crc = self._calc_crc(frame)
        frame.append(crc)
        return bytes(frame)
    
    def _make_error(self, error_code: int) -> bytes:
        return bytes([0xAA, 0xFF, 0x01, error_code, 
                     self._calc_crc([0xAA, 0xFF, 0x01, error_code])])
    
    def _process_command(self, cmd: bytes) -> bytes:
        if len(cmd) < 4:
            return self._make_error(0x01)
        
        if cmd[0] != 0xAA:
            return self._make_error(0x02)
        
        received_crc = cmd[-1]
        calculated_crc = self._calc_crc(list(cmd[:-1]))
        if received_crc != calculated_crc:
            print(f"  ⚠ CRC错误: 收到{received_crc:02X}, 计算{calculated_crc:02X}")
            return self._make_error(0x04)
        
        cmd_byte = cmd[1]
        
        handlers = {
            0x01: self._cmd_read_led,
            0x02: lambda: self._cmd_set_led(cmd),
            0x03: self._cmd_read_adc,
            0x04: lambda: self._cmd_set_pwm(cmd),
            0x05: self._cmd_read_button,
            0x06: lambda: self._cmd_control_buzzer(cmd),
            0x07: lambda: self._cmd_control_relay(cmd),
            0x08: self._cmd_read_temperature,
            0x09: self._cmd_read_humidity,
            0x0A: self._cmd_read_all_sensors,
            0x10: self._cmd_get_version,
            0x11: self._cmd_get_system_info,
            0x12: self._cmd_reset_system,
        }
        
        handler = handlers.get(cmd_byte)
        if handler:
            return handler()
        return self._make_error(0x03)
    
    def _cmd_read_led(self) -> bytes:
        data = [1 if self.led_state else 0]
        self._notify('led_changed', {'state': self.led_state})
        return self._make_response(0x01, data)
    
    def _cmd_set_led(self, cmd: bytes) -> bytes:
        if len(cmd) < 5:
            return self._make_error(0x01)
        state = cmd[3]
        self.led_state = bool(state)
        print(f"  → LED状态: {'开启' if self.led_state else '关闭'}")
        self._notify('led_changed', {'state': self.led_state})
        return self._make_response(0x02, [1 if self.led_state else 0])
    
    def _cmd_read_adc(self) -> bytes:
        data = [(self.adc_value >> 8) & 0xFF, self.adc_value & 0xFF]
        return self._make_response(0x03, data)
    
    def _cmd_set_pwm(self, cmd: bytes) -> bytes:
        if len(cmd) < 5:
            return self._make_error(0x01)
        pwm = cmd[3]
        self.led_pwm = min(100, max(0, pwm))
        self.led_state = self.led_pwm > 0
        print(f"  → PWM占空比: {self.led_pwm}%")
        self._notify('pwm_changed', {'pwm': self.led_pwm})
        return self._make_response(0x04, [self.led_pwm])
    
    def _cmd_read_button(self) -> bytes:
        self.button_state = random.choice([True, False])
        return self._make_response(0x05, [1 if self.button_state else 0])
    
    def _cmd_control_buzzer(self, cmd: bytes) -> bytes:
        if len(cmd) < 5:
            return self._make_error(0x01)
        state = cmd[3]
        self.buzzer_state = bool(state)
        print(f"  → 蜂鸣器: {'开启' if self.buzzer_state else '关闭'}")
        self._notify('buzzer_changed', {'state': self.buzzer_state})
        return self._make_response(0x06, [1 if self.buzzer_state else 0])
    
    def _cmd_control_relay(self, cmd: bytes) -> bytes:
        if len(cmd) < 5:
            return self._make_error(0x01)
        state = cmd[3]
        self.relay_state = bool(state)
        print(f"  → 继电器: {'开启' if self.relay_state else '关闭'}")
        self._notify('relay_changed', {'state': self.relay_state})
        return self._make_response(0x07, [1 if self.relay_state else 0])
    
    def _cmd_read_temperature(self) -> bytes:
        temp_int = int(self.temperature * 10)
        data = [(temp_int >> 8) & 0xFF, temp_int & 0xFF]
        return self._make_response(0x08, data)
    
    def _cmd_read_humidity(self) -> bytes:
        humid_int = int(self.humidity * 10)
        data = [(humid_int >> 8) & 0xFF, humid_int & 0xFF]
        return self._make_response(0x09, data)
    
    def _cmd_read_all_sensors(self) -> bytes:
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
        return self._make_response(0x0A, data)
    
    def _cmd_get_version(self) -> bytes:
        version_bytes = self.version.encode('ascii')[:16]
        return self._make_response(0x10, list(version_bytes))
    
    def _cmd_get_system_info(self) -> bytes:
        import time
        uptime = int(time.time() - self.start_time)
        info = [
            (uptime >> 24) & 0xFF, (uptime >> 16) & 0xFF,
            (uptime >> 8) & 0xFF, uptime & 0xFF,
            (self.packet_count >> 24) & 0xFF, (self.packet_count >> 16) & 0xFF,
            (self.packet_count >> 8) & 0xFF, self.packet_count & 0xFF,
        ]
        return self._make_response(0x11, info)
    
    def _cmd_reset_system(self) -> bytes:
        import time
        print("  → 系统复位...")
        self.led_state = False
        self.led_pwm = 0
        self.buzzer_state = False
        self.relay_state = False
        self.start_time = time.time()
        self.packet_count = 0
        self._notify('system_reset', {})
        return self._make_response(0x12, [0x01])
    
    def get_state(self) -> Dict:
        return {
            'led_state': self.led_state,
            'led_pwm': self.led_pwm,
            'adc_value': self.adc_value,
            'button_state': self.button_state,
            'buzzer_state': self.buzzer_state,
            'relay_state': self.relay_state,
            'temperature': self.temperature,
            'humidity': self.humidity,
            'packet_count': self.packet_count,
            'running': self.running,
        }
    
    def is_running(self) -> bool:
        return self.running


async def main_async(port: str = 'COM5', baudrate: int = 9600):
    STM32Simulator.reset_instance()
    sim = STM32Simulator.get_instance(port, baudrate)
    await sim.start()
    
    print("\n=== 模拟器运行中，按 Ctrl+C 停止 ===\n")
    
    try:
        while sim.is_running():
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n收到停止信号")
    finally:
        await sim.stop()


def main():
    import sys
    port = sys.argv[1] if len(sys.argv) > 1 else 'COM5'
    baudrate = int(sys.argv[2]) if len(sys.argv) > 2 else 9600
    
    asyncio.run(main_async(port, baudrate))


async def test_async():
    print("=== 协程模拟器测试 ===\n")
    
    STM32Simulator.reset_instance()
    sim = STM32Simulator.get_instance('COM5', 9600)
    
    def observer(event: str, data: Dict):
        print(f"[观察者] 事件: {event}, 数据: {data}")
    
    sim.add_observer(observer)
    
    print("1. 启动模拟器...")
    await sim.start()
    await asyncio.sleep(0.5)
    
    print("\n2. 读取状态...")
    state = sim.get_state()
    print(f"   LED: {state['led_state']}, ADC: {state['adc_value']}")
    
    print("\n3. 串口测试...")
    try:
        ser = serial.Serial('COM5', 9600, timeout=1)
        
        ser.write(bytes([0xAA, 0x01, 0x00, 0xAB]))
        await asyncio.sleep(0.1)
        resp = ser.read(10)
        print(f"   读取LED响应: {resp.hex(' ').upper()}")
        
        ser.write(bytes([0xAA, 0x02, 0x01, 0x01, 0xAE]))
        await asyncio.sleep(0.1)
        resp = ser.read(10)
        print(f"   LED开响应: {resp.hex(' ').upper()}")
        
        state = sim.get_state()
        print(f"   LED状态: {state['led_state']}")
        
        ser.close()
    except Exception as e:
        print(f"   串口测试失败: {e}")
    
    print("\n4. 停止模拟器...")
    await sim.stop()
    
    print("\n=== 测试完成 ===")


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        asyncio.run(test_async())
    else:
        main()