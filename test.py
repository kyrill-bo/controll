import pyautogui
import time
import threading
import sys
import termios
import tty
import select

# Movement settings
MOVE_SPEED = 10  # pixels per key press
UPDATE_INTERVAL = 0.05  # seconds

# Global flag to control the program
running = True

def get_key():
    """Get a single key press without requiring Enter"""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.cbreak(fd)
        # Check if input is available
        if select.select([sys.stdin], [], [], 0.01)[0]:
            ch = sys.stdin.read(1)
            return ch
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def handle_movement():
    """Handle WASD keyboard input for mouse movement"""
    global running
    
    while running:
        try:
            key = get_key()
            if key:
                current_x, current_y = pyautogui.position()
                
                if key.lower() == 'w':
                    # Move up
                    new_y = max(0, current_y - MOVE_SPEED)
                    pyautogui.moveTo(current_x, new_y)
                elif key.lower() == 's':
                    # Move down
                    screen_width, screen_height = pyautogui.size()
                    new_y = min(screen_height - 1, current_y + MOVE_SPEED)
                    pyautogui.moveTo(current_x, new_y)
                elif key.lower() == 'a':
                    # Move left
                    new_x = max(0, current_x - MOVE_SPEED)
                    pyautogui.moveTo(new_x, current_y)
                elif key.lower() == 'd':
                    # Move right
                    screen_width, screen_height = pyautogui.size()
                    new_x = min(screen_width - 1, current_x + MOVE_SPEED)
                    pyautogui.moveTo(new_x, current_y)
                elif key == '\x03':  # Ctrl+C
                    running = False
                    break
                    
        except KeyboardInterrupt:
            running = False
            break
        except Exception as e:
            # Continue running even if there's an error
            pass
        
        time.sleep(0.01)

def display_position():
    """Display current mouse position continuously"""
    global running
    
    while running:
        try:
            x, y = pyautogui.position()
            print(f"\rX={x} Y={y} | Use WASD to move cursor, Ctrl+C to exit", end="", flush=True)
            time.sleep(UPDATE_INTERVAL)
        except KeyboardInterrupt:
            running = False
            break

# Disable pyautogui fail-safe (optional, removes the need to move mouse to corner to stop)
pyautogui.FAILSAFE = False

print("Mouse Controller")
print("Use WASD keys to move the cursor")
print("Press Ctrl+C to exit\n")

try:
    # Start movement handler in a separate thread
    movement_thread = threading.Thread(target=handle_movement, daemon=True)
    movement_thread.start()
    
    # Run position display in main thread
    display_position()
    
except KeyboardInterrupt:
    pass
finally:
    running = False
    print("\nExiting...")
    sys.exit(0)