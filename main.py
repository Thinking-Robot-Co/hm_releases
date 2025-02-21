import RPi.GPIO as GPIO
import time

# Define GPIO pins
PINS = [23, 24, 25]

# Set up GPIO
GPIO.setmode(GPIO.BCM)  # Use Broadcom pin numbering
GPIO.setup(PINS, GPIO.OUT)

def wave_pattern(delay=0.2):
    """Creates a wave-like LED blinking effect."""
    for pin in PINS:
        GPIO.output(pin, GPIO.HIGH)
        time.sleep(delay)
        GPIO.output(pin, GPIO.LOW)
    
    for pin in reversed(PINS[:-1]):  # Reverse back without last LED
        GPIO.output(pin, GPIO.HIGH)
        time.sleep(delay)
        GPIO.output(pin, GPIO.LOW)

try:
    while True:
        wave_pattern()

except KeyboardInterrupt:
    print("\nExiting program...")

finally:
    GPIO.cleanup()  # Reset GPIO states on exit
