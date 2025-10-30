#V1.3 Hopefully fixed some proplems with anging aon the encoder requiring a pico power cycle.
from machine import Pin, UART
import time
import gc

# UART (TX=GP0, RX=GP1)
serial = UART(0, baudrate=115200, tx=0, rx=1)

# Encoder pins
pin_a = Pin(15, Pin.IN, Pin.PULL_DOWN)
pin_b = Pin(14, Pin.IN, Pin.PULL_DOWN)

# Modifier button (active low)
pin_modifier = Pin(13, Pin.IN, Pin.PULL_UP)

# Additional buttons (active low)
pin_override = Pin(16, Pin.IN, Pin.PULL_UP)
pin_pump_stop = Pin(17, Pin.IN, Pin.PULL_UP)

# Interrupt management - CRITICAL for reliability
interrupt_lock = False
encoder_pending = False
override_pending = False
pump_pending = False

# State tracking
encoder_state = {
    'last_a': pin_a.value(),
    'last_time': time.ticks_us(),
    'debounce_us': 1500,
    'interrupt_count': 0,
    'last_rate_check': time.ticks_ms(),
    'max_rate': 1000
}

button_state = {
    'override_last_time': time.ticks_ms(),
    'pump_last_time': time.ticks_ms(),
    'debounce_ms': 50
}

# Simple stats for debugging
stats = {'steps': 0, 'overrides': 0, 'pump_stops': 0, 'blocked': 0}

def safe_uart_write(message):
    """Safe UART write - exactly same format as original"""
    try:
        # Clear RX buffer to prevent overflow
        while serial.any():
            serial.read(1)
        serial.write(message)
        return True
    except:
        return False

def check_rate_limit():
    """Prevent interrupt flooding"""
    now = time.ticks_ms()
    if time.ticks_diff(now, encoder_state['last_rate_check']) >= 1000:
        encoder_state['interrupt_count'] = 0
        encoder_state['last_rate_check'] = now
        return True
    
    encoder_state['interrupt_count'] += 1
    return encoder_state['interrupt_count'] <= encoder_state['max_rate']

# Minimal interrupt handlers - just set flags
def encoder_isr(pin):
    global encoder_pending, interrupt_lock
    if not interrupt_lock and check_rate_limit():
        encoder_pending = True
    else:
        stats['blocked'] += 1

def override_isr(pin):
    global override_pending, interrupt_lock
    if not interrupt_lock:
        override_pending = True

def pump_stop_isr(pin):
    global pump_pending, interrupt_lock
    if not interrupt_lock:
        pump_pending = True

def process_encoder():
    """Process encoder - EXACT same output format as original"""
    global encoder_pending
    
    if not encoder_pending:
        return
    
    encoder_pending = False
    now = time.ticks_us()
    
    # Debounce check
    if time.ticks_diff(now, encoder_state['last_time']) < encoder_state['debounce_us']:
        return
    
    # Read current state
    a = pin_a.value()
    b = pin_b.value()
    
    if a == 1:  # Rising edge of A - EXACT same logic as original
        step = 10 if pin_modifier.value() == 0 else 1
        msg = f"+{step}" if b == 0 else f"-{step}"
        
        # EXACT same outputs as original
        print(msg)
        safe_uart_write(msg + "\n")
        stats['steps'] += 1
        
        encoder_state['last_time'] = now
    
    encoder_state['last_a'] = a

def process_override():
    """Process override - EXACT same output as original"""
    global override_pending
    
    if not override_pending:
        return
    
    override_pending = False
    now = time.ticks_ms()
    
    if time.ticks_diff(now, button_state['override_last_time']) < button_state['debounce_ms']:
        return
    
    button_state['override_last_time'] = now
    
    # Confirm still pressed - EXACT same logic as original
    time.sleep_ms(5)
    if pin_override.value() == 0:
        # EXACT same outputs as original
        safe_uart_write("OV\n")
        print("OV")
        stats['overrides'] += 1

def process_pump_stop():
    """Process pump stop - EXACT same output as original"""
    global pump_pending
    
    if not pump_pending:
        return
    
    pump_pending = False
    now = time.ticks_ms()
    
    if time.ticks_diff(now, button_state['pump_last_time']) < button_state['debounce_ms']:
        return
    
    button_state['pump_last_time'] = now
    
    # Confirm still pressed - EXACT same logic as original  
    time.sleep_ms(5)
    if pin_pump_stop.value() == 0:
        # EXACT same outputs as original
        safe_uart_write("PS\n")
        print("PS")
        stats['pump_stops'] += 1

def periodic_cleanup():
    """Prevent resource exhaustion"""
    gc.collect()
    # Clear any stuck RX data
    while serial.any():
        serial.read(1)

def system_reset():
    """Reset to clean state without restart"""
    global interrupt_lock, encoder_pending, override_pending, pump_pending
    
    interrupt_lock = True
    encoder_pending = False
    override_pending = False  
    pump_pending = False
    
    encoder_state['last_a'] = pin_a.value()
    encoder_state['last_time'] = time.ticks_us()
    encoder_state['interrupt_count'] = 0
    
    periodic_cleanup()
    time.sleep_ms(10)
    interrupt_lock = False

# Setup interrupts - same triggers as original
pin_a.irq(trigger=Pin.IRQ_RISING, handler=encoder_isr)
pin_override.irq(trigger=Pin.IRQ_FALLING, handler=override_isr)  
pin_pump_stop.irq(trigger=Pin.IRQ_FALLING, handler=pump_stop_isr)

print("Encoder + buttons monitor running...")  # EXACT same startup message

# Main loop
last_cleanup = time.ticks_ms()

try:
    while True:
        current_time = time.ticks_ms()
        
        # Process all pending interrupts in main thread
        process_encoder()
        process_override() 
        process_pump_stop()
        
        # Periodic maintenance every 5 seconds
        if time.ticks_diff(current_time, last_cleanup) > 5000:
            periodic_cleanup()
            last_cleanup = current_time
        
        # Check for debug commands (silent - no output change)
        if serial.any():
            try:
                cmd = serial.read(1).decode('utf-8')
                if cmd == 's':  # Silent stats
                    pass  # Could log internally if needed
                elif cmd == 'r':  # Silent reset
                    system_reset()
            except:
                pass
        
        time.sleep_ms(5)  # Responsive but not aggressive

except KeyboardInterrupt:
    interrupt_lock = True
except Exception:
    # Silent recovery attempt
    system_reset()