import RPi.GPIO as GPIO
import time
import sys

# Define GPIO pins for push buttons
BUTTONS = [17, 27, 22]

# Set up GPIO
GPIO.setmode(GPIO.BCM)  # Use Broadcom pin numbering
GPIO.setup(BUTTONS, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # Enable pull-up resistors

try:
    while True:
        # Read button states
        states = [GPIO.input(pin) for pin in BUTTONS]
        
        # Print in a single line (overwrite previous line)
        sys.stdout.write(f"\rBTN 17: {states[0]} | BTN 27: {states[1]} | BTN 22: {states[2]}")
        sys.stdout.flush()
        
        time.sleep(0.05)  # Small delay for stability (50ms)

except KeyboardInterrupt:
    print("\nExiting program...")

finally:
    GPIO.cleanup()  # Reset GPIO states on exit
