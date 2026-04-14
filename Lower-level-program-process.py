import serial
import time
import random
import hashlib
import struct
import multiprocessing
from datetime import datetime
from typing import Optional
from multiprocessing import Process, Lock, Value, Queue
import ctypes


class STM32Process:
    def __init__(self, port: str = 'COM5', baudrate: int = 9600):
        self.port = port
        self.baudrate = baudrate
        self.process: Optional[Process] = None
        self.lock = Lock()
        self.shared_state = None
        self.command_queue = Queue()
        self.response_queue = Queue()
        
    def _init_shared_state(self):
        self.shared_state = {
            'led_state': Value(ctypes.c_bool, False),
            'led_pwm': Value(ctypes.c_int, 0),
            'adc_value': Value(ctypes.c_int, 2048),
            'button_state': Value(ctypes.c_bool, False),
            'buzzer_state': Value(ctypes.c_bool, False),
            'relay_state': Value(ctypes.c_bool, False),
            'temperature': Value(ctypes.c_double, 25.0),
            'humidity': Value(ctypes.c_double, 60.0),
            'start_time': Value(ctypes.c_double, time.time()),
            'packet_count': Value(ctypes.c_int, 0),
            'running': Value(ctypes.c_bool, True),
        }
    
    @staticmethod
    def _worker(port: str, baudrate: int, shared_state: dict, 
                command_queue: Queue, response_queue: Queue, lock: Lock):
        ser = serial.Serial(port, baudrate, timeout=1)
        print(f"[子进程] STM32模拟器启动，监听 {port} @ {baudrate}")
        
        while shared_state['running'].value:
            if ser.in_waiting:
                cmd = ser.read(ser.in_waiting)
                shared_state['packet_count'].value += 1
                print(f"[子进程] 收到: {cmd.hex(' ').upper()}")
                
                with lock:
                    response = STM32Process._process_command(
                        cmd, shared_state, lock
                    )
                
                time.sleep(random.uniform(0.002, 0.015))
                ser.write(response)
                print(f"[子进程] 发送: {response.hex(' ').upper()}")
            
            if shared_state['packet_count'].value % 50 == 0:
                STM32Process._update_sensors(shared_state)
            
            time.sleep(0.01)
        
        ser.close()
        print("[子进程] 子进程结束")
    
    @staticmethod
    def _update_sensors(shared_state: dict):
        shared_state['temperature'].value += random.uniform(-0.5, 0.5)
        shared_state['temperature'].value = max(-40, min(85, shared_state['temperature'].value))
        shared_state['humidity'].value += random.uniform(-2, 2)
        shared_state['humidity'].value = max(0, min(100, shared_state['humidity'].value))
        shared_state['adc_value'].value = int(2048 + random.uniform(-500, 500))
        shared_state['adc_value'].value = max(0, min(4095, shared_state['adc_value'].value))
    
    @staticmethod
    def _calc_crc(data: list) -> int:
        return sum(data) & 0xFF
    
    @staticmethod
    def _make_response(cmd: int, data=None) -> bytes:
        frame = bytearray([0xAA, cmd])
        if data is not None:
            if isinstance(data, int):
                data = [data]
            frame.append(len(data))
            frame.extend(data)
        else:
            frame.append(0)
        crc = STM32Process._calc_crc(frame)
        frame.append(crc)
        return bytes(frame)
    
    @staticmethod
    def _make_error(error_code: int) -> bytes:
        return bytes([0xAA, 0xFF, 0x01, error_code, 
                     STM32Process._calc_crc([0xAA, 0xFF, 0x01, error_code])])
    
    @staticmethod
    def _process_command(cmd: bytes, shared_state: dict, lock: Lock) -> bytes:
        if len(cmd) < 4:
            return STM32Process._make_error(0x01)
        
        if cmd[0] != 0xAA:
            return STM32Process._make_error(0x02)
        
        received_crc = cmd[-1]
        calculated_crc = STM32Process._calc_crc(list(cmd[:-1]))
        if received_crc != calculated_crc:
            print(f"  ⚠ CRC错误: 收到{received_crc:02X}, 计算{calculated_crc:02X}")
            return STM32Process._make_error(0x04)
        
        cmd_byte = cmd[1]
        
        if cmd_byte == 0x01:
            data = [1 if shared_state['led_state'].value else 0]
            return STM32Process._make_response(0x01, data)
        
        elif cmd_byte == 0x02:
            if len(cmd) < 5:
                return STM32Process._make_error(0x01)
            state = cmd[3]
            shared_state['led_state'].value = bool(state)
            print(f"  → LED状态: {'开启' if shared_state['led_state'].value else '关闭'}")
            return STM32Process._make_response(0x02, [1 if shared_state['led_state'].value else 0])
        
        elif cmd_byte == 0x03:
            adc = shared_state['adc_value'].value
            data = [(adc >> 8) & 0xFF, adc & 0xFF]
            return STM32Process._make_response(0x03, data)
        
        elif cmd_byte == 0x04:
            if len(cmd) < 5:
                return STM32Process._make_error(0x01)
            pwm = cmd[3]
            shared_state['led_pwm'].value = min(100, max(0, pwm))
            shared_state['led_state'].value = shared_state['led_pwm'].value > 0
            print(f"  → PWM占空比: {shared_state['led_pwm'].value}%")
            return STM32Process._make_response(0x04, [shared_state['led_pwm'].value])
        
        elif cmd_byte == 0x05:
            shared_state['button_state'].value = random.choice([True, False])
            return STM32Process._make_response(0x05, [1 if shared_state['button_state'].value else 0])
        
        elif cmd_byte == 0x06:
            if len(cmd) < 5:
                return STM32Process._make_error(0x01)
            state = cmd[3]
            shared_state['buzzer_state'].value = bool(state)
            print(f"  → 蜂鸣器: {'开启' if shared_state['buzzer_state'].value else '关闭'}")
            return STM32Process._make_response(0x06, [1 if shared_state['buzzer_state'].value else 0])
        
        elif cmd_byte == 0x07:
            if len(cmd) < 5:
                return STM32Process._make_error(0x01)
            state = cmd[3]
            shared_state['relay_state'].value = bool(state)
            print(f"  → 继电器: {'开启' if shared_state['relay_state'].value else '关闭'}")
            return STM32Process._make_response(0x07, [1 if shared_state['relay_state'].value else 0])
        
        elif cmd_byte == 0x08:
            temp = int(shared_state['temperature'].value * 10)
            data = [(temp >> 8) & 0xFF, temp & 0xFF]
            return STM32Process._make_response(0x08, data)
        
        elif cmd_byte == 0x09:
            humid = int(shared_state['humidity'].value * 10)
            data = [(humid >> 8) & 0xFF, humid & 0xFF]
            return STM32Process._make_response(0x09, data)
        
        elif cmd_byte == 0x0A:
            data = [
                1 if shared_state['led_state'].value else 0,
                shared_state['led_pwm'].value,
                1 if shared_state['button_state'].value else 0,
                1 if shared_state['buzzer_state'].value else 0,
                1 if shared_state['relay_state'].value else 0,
                (shared_state['adc_value'].value >> 8) & 0xFF,
                shared_state['adc_value'].value & 0xFF,
                int(shared_state['temperature'].value * 10) & 0xFF,
                int(shared_state['humidity'].value * 10) & 0xFF,
            ]
            return STM32Process._make_response(0x0A, data)
        
        elif cmd_byte == 0x10:
            version = "v1.2.0"
            return STM32Process._make_response(0x10, list(version.encode('ascii')[:16]))
        
        elif cmd_byte == 0x11:
            uptime = int(time.time() - shared_state['start_time'].value)
            pkt_cnt = shared_state['packet_count'].value
            info = [
                (uptime >> 24) & 0xFF, (uptime >> 16) & 0xFF,
                (uptime >> 8) & 0xFF, uptime & 0xFF,
                (pkt_cnt >> 24) & 0xFF, (pkt_cnt >> 16) & 0xFF,
                (pkt_cnt >> 8) & 0xFF, pkt_cnt & 0xFF,
            ]
            return STM32Process._make_response(0x11, info)
        
        elif cmd_byte == 0x12:
            print("  → 系统复位...")
            shared_state['led_state'].value = False
            shared_state['led_pwm'].value = 0
            shared_state['buzzer_state'].value = False
            shared_state['relay_state'].value = False
            shared_state['start_time'].value = time.time()
            shared_state['packet_count'].value = 0
            return STM32Process._make_response(0x12, [0x01])
        
        else:
            return STM32Process._make_error(0x03)
    
    def start(self):
        if self.process is not None and self.process.is_alive():
            print("进程已在运行中")
            return
        
        self._init_shared_state()
        
        self.process = Process(
            target=STM32Process._worker,
            args=(self.port, self.baudrate, self.shared_state, 
                  self.command_queue, self.response_queue, self.lock)
        )
        self.process.start()
        print(f"[主进程] 子进程已启动，PID: {self.process.pid}")
    
    def stop(self):
        if self.shared_state is not None:
            self.shared_state['running'].value = False
        
        if self.process is not None and self.process.is_alive():
            self.process.join(timeout=2)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join()
        
        print("[主进程] 子进程已停止")
    
    def get_state(self) -> dict:
        if self.shared_state is None:
            return {}
        
        with self.lock:
            return {
                'led_state': self.shared_state['led_state'].value,
                'led_pwm': self.shared_state['led_pwm'].value,
                'adc_value': self.shared_state['adc_value'].value,
                'button_state': self.shared_state['button_state'].value,
                'buzzer_state': self.shared_state['buzzer_state'].value,
                'relay_state': self.shared_state['relay_state'].value,
                'temperature': self.shared_state['temperature'].value,
                'humidity': self.shared_state['humidity'].value,
                'packet_count': self.shared_state['packet_count'].value,
            }
    
    def is_running(self) -> bool:
        return self.process is not None and self.process.is_alive()


def main():
    import sys
    port = sys.argv[1] if len(sys.argv) > 1 else 'COM5'
    baudrate = int(sys.argv[2]) if len(sys.argv) > 2 else 9600
    
    simulator = STM32Process(port, baudrate)
    simulator.start()
    
    print("\n=== 进程运行中，按 Ctrl+C 停止 ===\n")
    
    try:
        while simulator.is_running():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[主进程] 收到停止信号")
    finally:
        simulator.stop()


def test_process():
    print("=== 多进程模拟器测试 ===\n")
    
    sim = STM32Process('COM5', 9600)
    
    print("1. 启动模拟器进程...")
    sim.start()
    time.sleep(0.5)
    
    print("\n2. 读取状态...")
    state = sim.get_state()
    print(f"   LED状态: {state.get('led_state', 'N/A')}")
    print(f"   ADC值: {state.get('adc_value', 'N/A')}")
    
    print("\n3. 通过串口发送命令测试...")
    try:
        ser = serial.Serial('COM6', 9600, timeout=1)
        
        print("   发送: AA 01 00 AB (读取LED)")
        ser.write(bytes([0xAA, 0x01, 0x00, 0xAB]))
        time.sleep(0.1)
        resp = ser.read(10)
        print(f"   接收: {resp.hex(' ').upper()}")
        
        print("   发送: AA 02 01 01 AE (LED开)")
        ser.write(bytes([0xAA, 0x02, 0x01, 0x01, 0xAE]))
        time.sleep(0.1)
        resp = ser.read(10)
        print(f"   接收: {resp.hex(' ').upper()}")
        
        state = sim.get_state()
        print(f"   LED状态: {state.get('led_state', 'N/A')}")
        
        ser.close()
    except Exception as e:
        print(f"   串口测试失败: {e}")
    
    print("\n4. 停止模拟器...")
    sim.stop()
    
    print("\n=== 测试完成 ===")


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        test_process()
    else:
        main()