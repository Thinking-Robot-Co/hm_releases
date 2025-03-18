# gpio_handler.py
import RPi.GPIO as GPIO

LED_PIN = 23

def setup_led():
    # Set up GPIO using BCM numbering
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(LED_PIN, GPIO.OUT)
    # Ensure the LED is off initially
    GPIO.output(LED_PIN, GPIO.LOW)

def led_on():
    GPIO.output(LED_PIN, GPIO.HIGH)

def led_off():
    GPIO.output(LED_PIN, GPIO.LOW)

def cleanup():
    GPIO.cleanup()
