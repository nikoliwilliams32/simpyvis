import simpy
import pygame
import threading
import time
import sys
import math

# --- Pygame Settings ---
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
FPS = 60
BG_COLOR = (255, 255, 255)  # White
ENTITY_COLOR = (0, 0, 255)  # Blue
TARGET_COLOR = (255, 0, 0)  # Red
TEXT_COLOR = (0, 0, 0)      # Black
ENTITY_RADIUS = 15

# --- Shared State Class ---
# This object is used to pass information from the SimPy thread
# to the Pygame (main) thread. We use a lock to prevent race conditions.
class SimulationState:
    def __init__(self):
        self.lock = threading.Lock()
        # Initial values
        self.start_pos = (50, SCREEN_HEIGHT // 2)
        self.target_pos = (50, SCREEN_HEIGHT // 2)
        self.real_start_time = time.time()
        self.duration = 0.0
        self.message = "Initializing..."
        self.running = True

# --- SimPy Simulation Process ---
# This function runs in a separate thread.
def vehicle_process(env, state):
    """
    A simple process that moves between waypoints and waits.
    'env' is the simpy.rt.RealtimeSimulation environment.
    'state' is the shared SimulationState object.
    """
    waypoints = [
        (50, SCREEN_HEIGHT // 2),
        (SCREEN_WIDTH - 50, SCREEN_HEIGHT // 2),
        (SCREEN_WIDTH - 50, 50),
        (50, 50),
        (50, SCREEN_HEIGHT - 50),
        (SCREEN_WIDTH - 50, SCREEN_HEIGHT - 50)
    ]
    idx = 0
    
    # Speed in pixels per second (matches the real-time factor)
    speed_px_per_sec = 150 

    while state.running:
        try:
            # 1. Define the next move
            start_pos = waypoints[idx % len(waypoints)]
            target_pos = waypoints[(idx + 1) % len(waypoints)]
            
            # 2. Calculate distance and duration
            distance = math.dist(start_pos, target_pos)
            duration = distance / speed_px_per_sec # Sim time = Real time

            # 3. Update the shared state (THIS IS THE "CAUSE")
            # We must use the lock to safely write to the state
            with state.lock:
                state.start_pos = start_pos
                state.target_pos = target_pos
                state.real_start_time = time.time() # Real-world start time
                state.duration = duration
                state.message = f"Sim: Moving to {target_pos}..."
            
            # 4. Tell SimPy to "wait" for the duration.
            # Because this is a RealtimeSimulation, this will sleep
            # the *thread* for 'duration' real-world seconds.
            yield env.timeout(duration)

            # 5. Arrived. Wait at the destination for a bit.
            wait_duration = 2.0 # 2 seconds
            with state.lock:
                state.message = f"Sim: Arrived! Waiting for {wait_duration}s"
            
            yield env.timeout(wait_duration)
            
            idx += 1
            
        except simpy.Interrupt:
            # This would be triggered if env.stop() was called
            print("Simulation process interrupted.")
            state.running = False
        except Exception as e:
            print(f"Simulation error: {e}")
            state.running = False

def run_simulation(state):
    """
    Target function for the simulation thread.
    Sets up and runs the SimPy environment.
    """
    try:
        # factor=1.0 means 1 unit of sim time = 1 second of real time
        env = simpy.rt.RealtimeSimulation(factor=1.0, strict=False)
        env.process(vehicle_process(env, state))
        # This will run as long as the process yields events,
        # or until env.stop() is called (which we don't do here,
        # we just exit the main loop and the daemon thread dies).
        env.run()
    except Exception as e:
        print(f"Sim environment failed: {e}")
        state.running = False

# --- Pygame Helper Functions ---
def draw_text(surface, text, pos, font, color=TEXT_COLOR):
    text_surface = font.render(text, True, color)
    surface.blit(text_surface, pos)

def draw_cross(surface, pos, color=TARGET_COLOR, size=10):
    x, y = int(pos[0]), int(pos[1])
    pygame.draw.line(surface, color, (x - size, y - size), (x + size, y + size), 3)
    pygame.draw.line(surface, color, (x - size, y + size), (x + size, y - size), 3)

def linear_interpolate(pos_a, pos_b, t):
    """
    Calculates the position at time 't' between A and B.
    t=0.0 -> pos_a
    t=1.0 -> pos_b
    """
    t = max(0.0, min(1.0, t)) # Clamp t to [0, 1]
    x = pos_a[0] + (pos_b[0] - pos_a[0]) * t
    y = pos_a[1] + (pos_b[1] - pos_a[1]) * t
    return (int(x), int(y))

# --- Main Function (Pygame Loop) ---
def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("SimPy Real-Time Visualization")
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 30)
    small_font = pygame.font.Font(None, 24)

    # 1. Create the shared state object
    state = SimulationState()

    # 2. Create and start the simulation thread
    #    daemon=True means the thread will automatically exit
    #    when the main program (pygame) exits.
    sim_thread = threading.Thread(target=run_simulation, args=(state,), daemon=True)
    sim_thread.start()

    running = True
    while running:
        # --- Event Handling ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        # --- Read from Shared State (with lock) ---
        # We copy all the values we need for this frame
        # inside a single lock to ensure consistency.
        with state.lock:
            start_pos = state.start_pos
            target_pos = state.target_pos
            real_start_time = state.real_start_time
            duration = state.duration
            message = state.message
            # If sim thread died, stop pygame
            if not state.running:
                running = False
        
        # --- Interpolation (THIS IS THE "FRAME") ---
        current_real_time = time.time()
        elapsed_real_time = current_real_time - real_start_time
        
        if duration > 0:
            fraction_complete = elapsed_real_time / duration
        else:
            fraction_complete = 1.0 # Instantly complete if duration is 0
            
        # Calculate the *current* visual position based on real time
        current_pos = linear_interpolate(start_pos, target_pos, fraction_complete)

        # --- Drawing ---
        screen.fill(BG_COLOR)
        
        # 1. Draw the Target (Set by SimPy)
        draw_cross(screen, target_pos, TARGET_COLOR, size=15)
        
        # 2. Draw the Entity (Interpolated "Frame")
        pygame.draw.circle(screen, ENTITY_COLOR, current_pos, ENTITY_RADIUS)
        
        # 3. Draw UI Text
        draw_text(screen, "SimPy Real-Time Simulation", (10, 10), font)
        draw_text(screen, f"FPS: {clock.get_fps():.1f}", (SCREEN_WIDTH - 100, 10), small_font)
        
        # 4. Draw Simulation Status
        draw_text(screen, "Simulation Status:", (10, SCREEN_HEIGHT - 70), small_font, (50,50,50))
        draw_text(screen, message, (15, SCREEN_HEIGHT - 45), font, (50,50,50))

        # 5. Draw Frame Info
        draw_text(screen, "Visualization (Frame) Info:", (SCREEN_WIDTH - 300, SCREEN_HEIGHT - 70), small_font, (50,50,50))
        draw_text(screen, f"Interpolation: {fraction_complete*100:.0f}%", (SCREEN_WIDTH - 300, SCREEN_HEIGHT - 45), font, (50,50,50))

        pygame.display.flip()
        clock.tick(FPS)

    # --- Cleanup ---
    print("Pygame loop exited. Shutting down.")
    # Tell the sim thread to stop (by setting the shared flag)
    with state.lock:
        state.running = False
    
    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()


