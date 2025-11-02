import base64
import io
import os
from dash import Dash, html, dcc
from dash.dependencies import Input, Output
import pygame
import numpy as np
import threading
import time
from PIL import Image
import plotly.graph_objects as go

# --- Pygame Settings ---
SCREEN_WIDTH = 400
SCREEN_HEIGHT = 300
FPS = 30
BG_COLOR = (255, 255, 255)
TANK_COLOR = (100, 149, 237)
WATER_COLOR = (0, 191, 255)

# Tank dimensions
TANK_WIDTH = 200
TANK_HEIGHT = 200
TANK_X = (SCREEN_WIDTH - TANK_WIDTH) // 2
TANK_Y = (SCREEN_HEIGHT - TANK_HEIGHT) // 2
MAX_VOLUME = 1000  # Liters


# Shared state for communication between Pygame and Dash
class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.volume = 0
        self.inflow = 50
        self.outflow = 30
        self._pygame_surface = None
        self.volume_history = []
        self.time_history = []
        self.running = True
        self.start_time = time.time()
        self.last_update = time.time()
        self.frame_count = 0

    def update_volume(self, volume):
        with self.lock:
            self.volume = max(0, min(MAX_VOLUME, volume))
            current_time = time.time() - self.start_time
            self.volume_history.append(self.volume)
            self.time_history.append(current_time)
            # Keep only last 100 points
            if len(self.volume_history) > 100:
                self.volume_history.pop(0)
                self.time_history.pop(0)

    def update_surface(self, surface):
        with self.lock:
            self._pygame_surface = surface
            self.frame_count += 1
            current_time = time.time()
            if current_time - self.last_update > 1.0:  # Print stats every second
                print(
                    f"Frame rate: {self.frame_count/(current_time - self.last_update):.1f} FPS"
                )
                print(f"Current volume: {self.volume:.1f}L")
                self.frame_count = 0
                self.last_update = current_time

    def get_surface(self):
        with self.lock:
            return self._pygame_surface

    def get_history(self):
        with self.lock:
            return self.time_history.copy(), self.volume_history.copy()


def draw_tank(surface, volume):
    """Draw the tank and water level"""
    # Draw tank border
    tank_rect = pygame.Rect(TANK_X, TANK_Y, TANK_WIDTH, TANK_HEIGHT)
    pygame.draw.rect(surface, TANK_COLOR, tank_rect, 3)

    # Calculate and draw water level
    fill_ratio = volume / MAX_VOLUME
    water_height = int(TANK_HEIGHT * fill_ratio)
    water_y = TANK_Y + TANK_HEIGHT - water_height
    if water_height > 0:
        water_rect = pygame.Rect(TANK_X, water_y, TANK_WIDTH, water_height)
        pygame.draw.rect(surface, WATER_COLOR, water_rect)


def render_tank(state, screen, font):
    """Render the current state to a surface"""
    screen.fill(BG_COLOR)

    # Draw tank and water
    draw_tank(screen, state.volume)

    # Draw volume text
    volume_text = font.render(f"{state.volume:.1f}L", True, (0, 0, 0))
    screen.blit(volume_text, (TANK_X, TANK_Y - 30))

    # Convert to PIL Image
    string_image = pygame.image.tostring(screen, "RGB")
    return Image.frombytes("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), string_image)


def pygame_loop(state):
    """Main Pygame loop running in a separate thread"""
    print("Initializing Pygame...")
    pygame.init()
    # Initialize Pygame in headless mode
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    pygame.display.init()
    pygame.font.init()

    print("Creating Pygame surface...")
    screen = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    clock = pygame.time.Clock()

    try:
        font = pygame.font.Font(None, 36)
    except pygame.error:
        print("Default font not available, using system font")
        font = pygame.font.SysFont("arial", 36)

    print("Pygame initialization complete.")

    while state.running:
        screen.fill(BG_COLOR)

        # Update volume based on flows
        with state.lock:
            current_volume = state.volume
            net_flow = state.inflow - state.outflow
            new_volume = current_volume + net_flow * (1 / FPS)
            state.update_volume(new_volume)

        # Draw tank
        draw_tank(screen, state.volume)

        # Draw volume text
        volume_text = font.render(f"{state.volume:.1f}L", True, (0, 0, 0))
        screen.blit(volume_text, (TANK_X, TANK_Y - 30))

        # Convert Pygame surface to image for Dash
        string_image = pygame.image.tostring(screen, "RGB")
        temp_surface = Image.frombytes(
            "RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), string_image
        )

        # Save to shared state
        with state.lock:
            state.pygame_surface = temp_surface

        clock.tick(FPS)

    pygame.quit()


# Initialize Dash app
app = Dash(__name__, update_title=None)  # Disable updating the browser title
state = SharedState()

print("Starting Pygame simulation thread...")
# Start Pygame thread
pygame_thread = threading.Thread(target=pygame_loop, args=(state,), daemon=True)
pygame_thread.start()

# Wait a bit for pygame to initialize
time.sleep(1)
print("Tank simulation started with:")

print("Setting up Dash layout...")
# Layout
app.layout = html.Div(
    [
        html.H1("Tank Simulation Dashboard"),
        html.Div(
            [
                html.Div(
                    [
                        html.H3("Tank Visualization"),
                        html.Img(
                            id="tank-image",
                            style={
                                "width": f"{SCREEN_WIDTH}px",
                                "height": f"{SCREEN_HEIGHT}px",
                                "border": "1px solid black",
                            },
                        ),
                    ],
                    style={
                        "display": "inline-block",
                        "vertical-align": "top",
                        "margin": "10px",
                        "padding": "10px",
                        "background-color": "#f8f9fa",
                    },
                ),
                html.Div(
                    [
                        html.H3("Volume History"),
                        dcc.Graph(id="volume-graph"),
                    ],
                    style={
                        "display": "inline-block",
                        "vertical-align": "top",
                        "margin": "10px",
                        "padding": "10px",
                        "background-color": "#f8f9fa",
                    },
                ),
            ]
        ),
        html.Div(
            [
                html.Label("Inflow Rate (L/s)"),
                dcc.Slider(
                    id="inflow-slider",
                    min=0,
                    max=100,
                    value=50,
                    marks={i: str(i) for i in range(0, 101, 20)},
                ),
                html.Label("Outflow Rate (L/s)"),
                dcc.Slider(
                    id="outflow-slider",
                    min=0,
                    max=100,
                    value=30,
                    marks={i: str(i) for i in range(0, 101, 20)},
                ),
            ],
            style={"width": "50%", "margin": "20px"},
        ),
        # Update more frequently than display for smoother simulation
        dcc.Interval(
            id="interval-component", interval=100, n_intervals=0  # Update every 100ms
        ),
    ]
)


@app.callback(Output("tank-image", "src"), Input("interval-component", "n_intervals"))
def update_tank_image(n):
    """Update the tank visualization"""
    surface = state.get_surface()
    if surface is None:
        print(f"No surface available yet (interval {n})")
        # Return a placeholder image or empty string
        return ""

    try:
        # Convert PIL image to base64
        buffer = io.BytesIO()
        surface.save(buffer, format="PNG")
        buffer.seek(0)
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{image_base64}"
    except Exception as e:
        print(f"Error updating tank image: {e}")
        return ""


@app.callback(
    Output("volume-graph", "figure"), Input("interval-component", "n_intervals")
)
def update_volume_graph(n):
    """Update the volume history graph"""
    print(f"Updating volume graph (interval {n})")
    times, volumes = state.get_history()

    if not times or not volumes:
        print("No volume history data available yet")
        # Return empty graph with proper ranges
        return {
            "data": [],
            "layout": go.Layout(
                title="Tank Volume History",
                xaxis={"title": "Time (s)", "range": [0, 10]},
                yaxis={"title": "Volume (L)", "range": [0, MAX_VOLUME]},
                height=300,
            ),
        }

    print(f"Current volume: {volumes[-1]:.1f}L, Time: {times[-1]:.1f}s")
    return {
        "data": [go.Scatter(x=times, y=volumes, mode="lines", name="Tank Volume")],
        "layout": go.Layout(
            title="Tank Volume History",
            xaxis={
                "title": "Time (s)",
                "range": [max(0, times[-1] - 30), times[-1] + 1],
            },
            yaxis={"title": "Volume (L)", "range": [0, MAX_VOLUME]},
            height=300,
        ),
    }


@app.callback(
    Output("interval-component", "interval"),
    [Input("inflow-slider", "value"), Input("outflow-slider", "value")],
)
def update_flows(inflow, outflow):
    """Update flow rates from sliders"""
    with state.lock:
        state.inflow = inflow if inflow is not None else state.inflow
        state.outflow = outflow if outflow is not None else state.outflow
        print(
            f"Flow rates updated - Inflow: {state.inflow:.1f} L/s, Outflow: {state.outflow:.1f} L/s"
        )
    return 100  # Update every 100ms


if __name__ == "__main__":
    print("Starting Dash server...")
    # Use host='0.0.0.0' to make it accessible from other computers if needed
    app.run(debug=True, dev_tools_hot_reload=False, use_reloader=False)
