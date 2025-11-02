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
TANK_COLOR = (100, 149, 237)  # Cornflower Blue
TANK_BORDER_COLOR = (70, 130, 180)  # Steel Blue
WATER_COLOR = (0, 191, 255)  # Deep Sky Blue
TEXT_COLOR = (0, 0, 0)  # Black

# Tank dimensions
TANK_WIDTH = 200
TANK_HEIGHT = 400
TANK_X = (SCREEN_WIDTH - TANK_WIDTH) // 2
TANK_Y = (SCREEN_HEIGHT - TANK_HEIGHT) // 2
MAX_VOLUME = 1000  # Liters


@dataclass
class SimulationState:
    def __init__(self):
        self.lock = threading.Lock()
        self.current_volume = 0  # Current volume in liters
        self.inflow_rate = 50  # Liters per second
        self.outflow_rate = 30  # Liters per second
        self.message = "Initializing..."
        self.running = True
        self.factor = 1.0  # Simulation speed factor

    def update_volume(self, volume):
        """Thread-safe volume update"""
        with self.lock:
            self.current_volume = max(0, min(MAX_VOLUME, volume))


def tank_process(env, state):
    """
    SimPy process that simulates tank filling and emptying.
    """
    update_interval = 1 / 60  # Update 60 times per second in simulation time

    with state.lock:
        is_running = state.running
        volume = state.current_volume

    while is_running:
        try:
            # Get current rates
            with state.lock:
                inflow = state.inflow_rate
                outflow = state.outflow_rate

            # Calculate volume change - use raw rates since SimPy handles the time factor
            net_flow = inflow - outflow
            volume += net_flow * update_interval

            # Update volume in shared state
            state.update_volume(volume)

            # Update message
            with state.lock:
                if net_flow > 0:
                    state.message = f"Tank filling at {net_flow:.1f} L/s"
                elif net_flow < 0:
                    state.message = f"Tank emptying at {abs(net_flow):.1f} L/s"
                else:
                    state.message = "Tank level stable"

            # Wait for next update
            yield env.timeout(update_interval)

            with state.lock:
                is_running = state.running
                volume = state.current_volume

        except simpy.Interrupt:
            print("Simulation process interrupted.")
            break
        except Exception as e:
            print(f"Simulation error: {e}")
            break


def create_env(factor):
    """Create a new RealtimeEnvironment with the given factor"""
    # Invert the factor because SimPy's factor works opposite to what we want
    # A factor of 2 in SimPy makes it run twice as slow, we want it twice as fast
    return simpy.rt.RealtimeEnvironment(factor=1 / factor, strict=False)


def run_simulation(state):
    """
    Target function for the simulation thread.
    """
    try:
        with state.lock:
            current_factor = state.factor
            is_running = state.running

        env = create_env(current_factor)
        env.process(tank_process(env, state))
        check_interval = 0.1

        while is_running:
            try:
                with state.lock:
                    new_factor = state.factor

                if new_factor != current_factor:
                    print(f"Changing simulation speed to {new_factor}x")
                    current_factor = new_factor
                    # Store current volume
                    current_volume = state.current_volume
                    # Create new environment with new speed
                    env = create_env(current_factor)
                    # Restart process with current volume
                    state.current_volume = current_volume
                    env.process(tank_process(env, state))

                env.run(until=env.now + check_interval)

            except Exception as e:
                print(f"Sim environment failed: {e}")
                if not isinstance(e, simpy.Interrupt):
                    state.running = False
                    break

            with state.lock:
                is_running = state.running

    except Exception as e:
        print(f"Sim thread failed: {e}")
        state.running = False


# --- Pygame Helper Functions ---
def draw_text(surface, text, pos, font, color=TEXT_COLOR):
    text_surface = font.render(text, True, color)
    surface.blit(text_surface, pos)


def draw_slider(
    surface, pos, width, height, value, min_val, max_val, color=(100, 100, 100)
):
    """Draw a horizontal slider control"""
    track_rect = pygame.Rect(pos[0], pos[1] + height // 2 - 2, width, 4)
    pygame.draw.rect(surface, color, track_rect)

    value_normalized = (value - min_val) / (max_val - min_val)
    handle_x = pos[0] + int(value_normalized * width)
    handle_y = pos[1] + height // 2
    handle_radius = height // 2

    pygame.draw.circle(surface, color, (handle_x, handle_y), handle_radius)
    return pygame.Rect(pos[0], pos[1], width, height)


def update_slider_value(slider_rect, mouse_pos, min_val, max_val):
    """Calculate the slider value based on mouse position"""
    if not slider_rect.collidepoint(mouse_pos):
        return None

    rel_x = mouse_pos[0] - slider_rect.x
    normalized = max(0.0, min(1.0, rel_x / slider_rect.width))
    return min_val + (max_val - min_val) * normalized


def draw_tank(surface, volume, max_volume):
    """Draw the tank and its contents"""
    # Draw tank border
    tank_rect = pygame.Rect(TANK_X, TANK_Y, TANK_WIDTH, TANK_HEIGHT)
    pygame.draw.rect(surface, TANK_BORDER_COLOR, tank_rect, 3)

    # Calculate water height based on volume
    fill_ratio = volume / max_volume
    water_height = int(TANK_HEIGHT * fill_ratio)
    water_y = TANK_Y + TANK_HEIGHT - water_height

    # Draw water
    if water_height > 0:
        water_rect = pygame.Rect(TANK_X, water_y, TANK_WIDTH, water_height)
        pygame.draw.rect(surface, WATER_COLOR, water_rect)


def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Tank Simulation")
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 30)
    small_font = pygame.font.Font(None, 24)

    # Create shared state
    state = SimulationState()

    # Start simulation thread
    sim_thread = threading.Thread(target=run_simulation, args=(state,), daemon=True)
    sim_thread.start()

    # Define sliders
    speed_slider_pos = (50, 50)
    inflow_slider_pos = (50, 100)
    outflow_slider_pos = (50, 150)
    slider_width = 200
    slider_height = 20

    # Slider ranges
    min_factor = 0.1
    max_factor = 5.0
    min_flow = 0
    max_flow = 100

    # Slider state
    sliders = {
        "speed": {"rect": None, "active": False},
        "inflow": {"rect": None, "active": False},
        "outflow": {"rect": None, "active": False},
    }

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    for slider in sliders.values():
                        if slider["rect"] and slider["rect"].collidepoint(event.pos):
                            slider["active"] = True
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:
                    for slider in sliders.values():
                        slider["active"] = False
            elif event.type == pygame.MOUSEMOTION:
                # Handle slider dragging
                if sliders["speed"]["active"]:
                    new_factor = update_slider_value(
                        sliders["speed"]["rect"], event.pos, min_factor, max_factor
                    )
                    if new_factor is not None:
                        with state.lock:
                            state.factor = new_factor
                if sliders["inflow"]["active"]:
                    new_inflow = update_slider_value(
                        sliders["inflow"]["rect"], event.pos, min_flow, max_flow
                    )
                    if new_inflow is not None:
                        with state.lock:
                            state.inflow_rate = new_inflow
                if sliders["outflow"]["active"]:
                    new_outflow = update_slider_value(
                        sliders["outflow"]["rect"], event.pos, min_flow, max_flow
                    )
                    if new_outflow is not None:
                        with state.lock:
                            state.outflow_rate = new_outflow

        # Get current state
        with state.lock:
            current_volume = state.current_volume
            message = state.message
            if not state.running:
                running = False

        # Drawing
        screen.fill(BG_COLOR)

        # Draw tank
        draw_tank(screen, current_volume, MAX_VOLUME)

        # Draw sliders
        sliders["speed"]["rect"] = draw_slider(
            screen,
            speed_slider_pos,
            slider_width,
            slider_height,
            state.factor,
            min_factor,
            max_factor,
        )
        sliders["inflow"]["rect"] = draw_slider(
            screen,
            inflow_slider_pos,
            slider_width,
            slider_height,
            state.inflow_rate,
            min_flow,
            max_flow,
        )
        sliders["outflow"]["rect"] = draw_slider(
            screen,
            outflow_slider_pos,
            slider_width,
            slider_height,
            state.outflow_rate,
            min_flow,
            max_flow,
        )

        # Draw labels
        draw_text(
            screen,
            f"Simulation Speed: {state.factor:.1f}x",
            (speed_slider_pos[0], speed_slider_pos[1] - 20),
            small_font,
        )
        draw_text(
            screen,
            f"Inflow Rate: {state.inflow_rate:.1f} L/s",
            (inflow_slider_pos[0], inflow_slider_pos[1] - 20),
            small_font,
        )
        draw_text(
            screen,
            f"Outflow Rate: {state.outflow_rate:.1f} L/s",
            (outflow_slider_pos[0], outflow_slider_pos[1] - 20),
            small_font,
        )

        # Draw volume and status
        draw_text(
            screen,
            f"Current Volume: {current_volume:.1f} L",
            (TANK_X, TANK_Y + TANK_HEIGHT + 20),
            font,
        )
        draw_text(screen, message, (TANK_X, TANK_Y + TANK_HEIGHT + 50), font)
        draw_text(
            screen, f"FPS: {clock.get_fps():.1f}", (SCREEN_WIDTH - 100, 10), small_font
        )

        pygame.display.flip()
        clock.tick(FPS)

    # Cleanup
    with state.lock:
        state.running = False

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
