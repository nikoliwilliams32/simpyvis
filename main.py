import simpy.rt
import pygame
import threading
import time
import sys
import math
from dataclasses import dataclass

# --- Pygame Settings ---
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
FPS = 60
BG_COLOR = (255, 255, 255)  # White
ENTITY_COLOR = (0, 0, 255)  # Blue
TARGET_COLOR = (255, 0, 0)  # Red
TEXT_COLOR = (0, 0, 0)  # Black
ENTITY_RADIUS = 15


# --- Shared State Class ---
# This object is used to pass information from the SimPy thread
# to the Pygame (main) thread. We use a lock to prevent race conditions.
@dataclass
class SimulationState:
    def __init__(self):
        self.lock = threading.Lock()
        # Initial values
        self.current_pos = (50, SCREEN_HEIGHT // 2)  # Current position of the entity
        self.target_pos = (50, SCREEN_HEIGHT // 2)  # Next target position
        self.message = "Initializing..."
        self.running = True
        self.factor = 1.0  # Simulation speed factor

    def update_position(self, pos):
        """Thread-safe position update"""
        with self.lock:
            self.current_pos = pos


# --- SimPy Simulation Process ---
# This function runs in a separate thread.
def create_env(factor):
    """Create a new RealtimeEnvironment with the given factor"""
    return simpy.rt.RealtimeEnvironment(factor=factor, strict=False)


def vehicle_process(env, state, start_from=None, continue_to=None):
    """
    A simple process that moves between waypoints and waits.
    'env' is the simpy.rt.RealtimeSimulation environment.
    'state' is the shared SimulationState object.
    'start_from' optional position to start from (for factor changes)
    'continue_to' optional target to continue moving towards after factor change
    """
    waypoints = [
        (50, SCREEN_HEIGHT // 2),
        (SCREEN_WIDTH - 50, SCREEN_HEIGHT // 2),
        (SCREEN_WIDTH - 50, 50),
        (50, 50),
        (50, SCREEN_HEIGHT - 50),
        (SCREEN_WIDTH - 50, SCREEN_HEIGHT - 50),
    ]

    # If continuing a movement, find the target waypoint's index
    if continue_to:
        idx = 0
        min_dist = float("inf")
        for i, wp in enumerate(waypoints):
            dist = math.dist(continue_to, wp)
            if dist < min_dist:
                min_dist = dist
                idx = i
        # Move index back one since we'll increment it before using
        idx = (idx - 1) % len(waypoints)
    # If starting from a specific position but no target, find closest waypoint
    elif start_from:
        idx = 0
        min_dist = float("inf")
        for i, wp in enumerate(waypoints):
            dist = math.dist(start_from, wp)
            if dist < min_dist:
                min_dist = dist
                idx = i
    else:
        idx = 0

    base_speed = 150  # Base speed in pixels per second

    with state.lock:
        is_running = state.running

    while is_running:
        try:
            # Get current speed based on current factor
            with state.lock:
                current_factor = state.factor

            # 1. Get next waypoint
            current_pos = start_from if start_from else waypoints[idx % len(waypoints)]
            target_pos = (
                continue_to if continue_to else waypoints[(idx + 1) % len(waypoints)]
            )
            start_from = None  # Only use start_from once
            continue_to = None  # Only use continue_to once

            # Update shared state with new target and movement message
            with state.lock:
                state.target_pos = target_pos
                state.message = f"Sim: Moving to {target_pos}..."

            # 2. Move to target
            speed_px_per_sec = base_speed * current_factor  # Keep base speed constant
            distance = math.dist(current_pos, target_pos)
            # Adjust duration based on factor - faster factor = shorter duration
            total_duration = distance / speed_px_per_sec

            # Fixed update interval for smooth animation (in simulation time)
            update_interval = 1 / 360  # 60 updates per second

            start_time = env.now
            while (env.now - start_time) * current_factor < total_duration:
                # Calculate current position
                progress = ((env.now - start_time) / total_duration) * current_factor
                x = current_pos[0] + (target_pos[0] - current_pos[0]) * progress
                y = current_pos[1] + (target_pos[1] - current_pos[1]) * progress
                state.update_position((int(x), int(y)))

                # Wait a short interval before next update
                yield env.timeout(update_interval)

                # No need to check for factor changes - the environment will be recreated
                # when factor changes, and this process will be interrupted

            # Ensure we reach the exact target
            state.update_position(target_pos)

            # 3. Wait at destination
            wait_duration = 2.0  # 2 seconds
            with state.lock:
                state.message = (
                    f"Sim: Arrived! Waiting for {wait_duration/current_factor}s"
                )

            yield env.timeout(wait_duration / current_factor / current_factor)
            idx += 1

            with state.lock:
                is_running = state.running

        except simpy.Interrupt:
            # This would be triggered if env.stop() was called
            print("Simulation process interrupted.")
            with state.lock:
                state.running = False
                is_running = False
        except Exception as e:
            print(f"Simulation error: {e}")
            with state.lock:
                state.running = False
                is_running = False


def run_simulation(state):
    """
    Target function for the simulation thread.
    Sets up and runs the SimPy environment.
    """
    try:
        with state.lock:
            current_factor = state.factor
            is_running = state.running

        # Initial environment setup
        env = create_env(current_factor)
        env.process(vehicle_process(env, state))
        last_pos = None
        check_interval = 0.1  # Check for factor changes every 0.1 seconds

        while is_running:
            try:
                # Store current state before potential environment switch
                with state.lock:
                    last_pos = state.current_pos
                    last_target = state.target_pos
                    new_factor = state.factor

                # Check if factor changed
                if new_factor != current_factor:
                    # Create new environment with updated factor
                    current_factor = new_factor
                    env = create_env(current_factor)
                    with state.lock:
                        state.message = f"Speed changed to {current_factor:.1f}x"

                    # Start new process from current position with current target
                    env.process(
                        vehicle_process(
                            env, state, start_from=last_pos, continue_to=last_target
                        )
                    )

                # Run simulation for a short interval
                env.run(until=env.now + check_interval)

            except Exception as e:
                print(f"Sim environment failed: {e}")
                if not isinstance(e, simpy.Interrupt):
                    state.running = False
                    break
                # On interrupt, we'll create a new environment on next loop

    except Exception as e:
        print(f"Sim thread failed: {e}")
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
    t = max(0.0, min(1.0, t))  # Clamp t to [0, 1]
    x = pos_a[0] + (pos_b[0] - pos_a[0]) * t
    y = pos_a[1] + (pos_b[1] - pos_a[1]) * t
    return (int(x), int(y))


# --- Slider Helper Functions ---
def draw_slider(
    surface, pos, width, height, value, min_val, max_val, color=(100, 100, 100)
):
    """
    Draw a horizontal slider control.
    Returns the slider's rect for hit testing.
    """
    # Draw the track
    track_rect = pygame.Rect(pos[0], pos[1] + height // 2 - 2, width, 4)
    pygame.draw.rect(surface, color, track_rect)

    # Calculate handle position
    value_normalized = (value - min_val) / (max_val - min_val)
    handle_x = pos[0] + int(value_normalized * width)
    handle_y = pos[1] + height // 2
    handle_radius = height // 2

    # Draw the handle
    pygame.draw.circle(surface, color, (handle_x, handle_y), handle_radius)

    # Return the entire slider rect for hit testing
    return pygame.Rect(pos[0], pos[1], width, height)


def update_slider_value(slider_rect, mouse_pos, min_val, max_val):
    """
    Calculate the slider value based on mouse position.
    Returns the new value between min_val and max_val.
    """
    if not slider_rect.collidepoint(mouse_pos):
        return None

    rel_x = mouse_pos[0] - slider_rect.x
    normalized = max(0.0, min(1.0, rel_x / slider_rect.width))
    return min_val + (max_val - min_val) * normalized


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

    # Define slider properties
    slider_pos = (SCREEN_WIDTH - 300, 50)
    slider_width = 200
    slider_height = 20
    min_factor = 0.1  # 10x slower
    max_factor = 50.0  # 5x faster
    slider_rect = None
    slider_active = False

    running = True
    while running:
        # --- Event Handling ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # Left click
                    if slider_rect and slider_rect.collidepoint(event.pos):
                        slider_active = True
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:  # Left click
                    slider_active = False
            elif event.type == pygame.MOUSEMOTION:
                if slider_active:
                    new_factor = update_slider_value(
                        slider_rect, event.pos, min_factor, max_factor
                    )
                    print(f"New factor: {new_factor}")
                    if new_factor is not None:
                        with state.lock:
                            state.factor = new_factor

        # --- Read from Shared State (with lock) ---
        # We copy all the values we need for this frame
        # inside a single lock to ensure consistency.
        with state.lock:
            current_pos = state.current_pos
            target_pos = state.target_pos
            message = state.message
            # If sim thread died, stop pygame
            if not state.running:
                running = False

        # --- Drawing ---
        screen.fill(BG_COLOR)

        # 1. Draw the Target (Set by SimPy)
        draw_cross(screen, target_pos, TARGET_COLOR, size=15)

        # 2. Draw the Entity (Interpolated "Frame")
        pygame.draw.circle(screen, ENTITY_COLOR, current_pos, ENTITY_RADIUS)

        # 3. Draw UI Text
        draw_text(screen, "SimPy Real-Time Simulation", (10, 10), font)
        draw_text(
            screen, f"FPS: {clock.get_fps():.1f}", (SCREEN_WIDTH - 100, 10), small_font
        )

        # Draw the speed control slider
        slider_rect = draw_slider(
            screen,
            slider_pos,
            slider_width,
            slider_height,
            state.factor,
            min_factor,
            max_factor,
        )
        draw_text(
            screen,
            f"Speed: {state.factor:.1f}x",
            (slider_pos[0], slider_pos[1] - 20),
            small_font,
        )

        # 4. Draw Simulation Status
        draw_text(
            screen,
            "Simulation Status:",
            (10, SCREEN_HEIGHT - 70),
            small_font,
            (50, 50, 50),
        )
        draw_text(screen, message, (15, SCREEN_HEIGHT - 45), font, (50, 50, 50))

        # 5. Draw Frame Info
        draw_text(
            screen,
            "Visualization Info:",
            (SCREEN_WIDTH - 300, SCREEN_HEIGHT - 70),
            small_font,
            (50, 50, 50),
        )
        if target_pos != current_pos:
            distance = math.dist(current_pos, target_pos)
            draw_text(
                screen,
                f"Distance to target: {distance:.0f}px",
                (SCREEN_WIDTH - 300, SCREEN_HEIGHT - 45),
                font,
                (50, 50, 50),
            )

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
