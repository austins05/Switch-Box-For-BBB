# V1.5 - Auto UART recovery + simple 10s heartbeat (no stats)
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

# Interrupt flags
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

# Debug stats
stats = {'steps': 0, 'overrides': 0, 'pump_stops': 0, 'blocked': 0}

# ---------------------------------------------------------------
# UART health management
# ---------------------------------------------------------------
def ensure_uart_alive():
    """Check and reinit UART if it crashed or got desynced."""
    global serial
    try:
        serial.write(b"")  # test write
        return True
    except Exception as e:
        print("UART error, reinitializing:", e)
        try:
            serial.deinit()
        except:
            pass
        time.sleep_ms(50)
        try:
            serial = UART(0, baudrate=115200, tx=0, rx=1)
            print("UART reinitialized")
            return True
        except Exception as e:
            print("UART reinit failed:", e)
            return False

def safe_uart_write(message):
    """Safe UART write - retries if UART is wedged."""
    try:
        while serial.any():
            serial.read(1)
        serial.write(message)
        return True
    except Exception as e:
        print("UART write failed:", e)
        ensure_uart_alive()
        return False

# ---------------------------------------------------------------
# Interrupt handlers
# ---------------------------------------------------------------
def check_rate_limit():
    """Prevent interrupt flooding."""
    now = time.ticks_ms()
    if time.ticks_diff(now, encoder_state['last_rate_check']) >= 1000:
        encoder_state['interrupt_count'] = 0
        encoder_state['last_rate_check'] = now
        return True
    encoder_state['interrupt_count'] += 1
    return encoder_state['interrupt_count'] <= encoder_state['max_rate']

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

# ---------------------------------------------------------------
# Processing routines
# ---------------------------------------------------------------
def process_encoder():
    global encoder_pending
    if not encoder_pending:
        return
    encoder_pending = False
    now = time.ticks_us()
    if time.ticks_diff(now, encoder_state['last_time']) < encoder_state['debounce_us']:
        return
    a = pin_a.value()
    b = pin_b.value()
    if a == 1:  # Rising edge of A
        step = 10 if pin_modifier.value() == 0 else 1
        msg = f"+{step}" if b == 0 else f"-{step}"
        print(msg)
        safe_uart_write(msg + "\n")
        stats['steps'] += 1
        encoder_state['last_time'] = now
    encoder_state['last_a'] = a

def process_override():
    global override_pending
    if not override_pending:
        return
    override_pending = False
    now = time.ticks_ms()
    if time.ticks_diff(now, button_state['override_last_time']) < button_state['debounce_ms']:
        return
    button_state['override_last_time'] = now
    time.sleep_ms(5)
    if pin_override.value() == 0:
        safe_uart_write("OV\n")
        print("OV")
        stats['overrides'] += 1

def process_pump_stop():
    global pump_pending
    if not pump_pending:
        return
    pump_pending = False
    now = time.ticks_ms()
    if time.ticks_diff(now, button_state['pump_last_time']) < button_state['debounce_ms']:
        return
    button_state['pump_last_time'] = now
    time.sleep_ms(5)
    if pin_pump_stop.value() == 0:
        safe_uart_write("PS\n")
        print("PS")
        stats['pump_stops'] += 1

def periodic_cleanup():
    """Prevent resource exhaustion."""
    gc.collect()
    while serial.any():
        serial.read(1)

def system_reset():
    """Reset to clean state without restart."""
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

# ---------------------------------------------------------------
# Setup interrupts
# ---------------------------------------------------------------
pin_a.irq(trigger=Pin.IRQ_RISING, handler=encoder_isr)
pin_override.irq(trigger=Pin.IRQ_FALLING, handler=override_isr)
pin_pump_stop.irq(trigger=Pin.IRQ_FALLING, handler=pump_stop_isr)

print("Encoder + buttons monitor running...")

# ---------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------
last_cleanup = time.ticks_ms()
last_status = time.ticks_ms()

try:
    while True:
        current_time = time.ticks_ms()

        # Process all pending interrupts
        process_encoder()
        process_override()
        process_pump_stop()

        # Maintenance every 5 seconds
        if time.ticks_diff(current_time, last_cleanup) > 5000:
            periodic_cleanup()
            ensure_uart_alive()
            last_cleanup = current_time

        # Heartbeat every 10 seconds
        if time.ticks_diff(current_time, last_status) > 10000:
            safe_uart_write("OK\n")
            print("OK")
            last_status = current_time

        # Check incoming commands
        if serial.any():
            try:
                cmd = serial.read(1).decode('utf-8')
                if cmd == 'r':  # manual reset command
                    system_reset()
            except:
                ensure_uart_alive()

        time.sleep_ms(5)

except KeyboardInterrupt:
    interrupt_lock = True
except Exception as e:
    print("Main loop exception:", e)
    ensure_uart_alive()
    system_reset()
