from djitellopy.tello import Tello
import cv2
import pygame
import numpy as np
import time
import threading
from typing import Dict, List, Tuple

# Speed of the drone
S = 60
# Frames per second of the pygame window display
FPS = 120

class VideoStreamHandler:
    def __init__(self, tello, port):
        self.tello = tello
        self.port = port
        self.frame = None
        self.stopped = False
        self.retry_count = 0
        self.max_retries = 3
        self.retry_delay = 2
        self.lock = threading.Lock()
        
    def start(self):
        self.stopped = False
        threading.Thread(target=self._update_frame, daemon=True).start()
        return self
        
    def _update_frame(self):
        while not self.stopped:
            try:
                frame_read = self.tello.get_frame_read(port=self.port)
                while not self.stopped:
                    current_frame = frame_read.frame
                    if current_frame is not None:
                        with self.lock:
                            self.frame = current_frame.copy()
                    time.sleep(1/FPS)
            except Exception as e:
                print(f"Error in video stream: {str(e)}")
                self.retry_count += 1
                if self.retry_count > self.max_retries:
                    print("Max retries exceeded for video stream")
                    self.stopped = True
                    break
                print(f"Retrying video stream... ({self.retry_count}/{self.max_retries})")
                time.sleep(self.retry_delay)
                try:
                    # Try to reconnect the video stream
                    self.tello.streamoff()
                    time.sleep(0.5)
                    self.tello.streamon()
                    time.sleep(0.5)
                except:
                    print("Failed to reconnect video stream")
                    
    def get_frame(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None
            
    def stop(self):
        self.stopped = True

class MultiTelloFrontEnd:
    def __init__(self, tello_configs: List[Tuple[str, int]]):
        """
        Initialize MultiTelloFrontEnd
        Args:
            tello_configs: List of tuples containing (ip, video_port) for each Tello
        """
        # Init pygame
        pygame.init()

        # Calculate window size and grid layout
        self.num_drones = len(tello_configs)
        # Calculate cols and rows needed
        self.cols = min(2, self.num_drones)  # Maximum 2 columns
        self.rows = (self.num_drones + 1) // 2  # Ceiling division to get rows needed
        
        # Calculate total window size
        self.window_width = 960 * self.cols
        self.window_height = 720 * self.rows
        
        print(f"Window size: {self.window_width}x{self.window_height}, Grid: {self.cols}x{self.rows}")

        # Create pygame window
        pygame.display.set_caption("Multi Tello Video Stream")
        self.screen = pygame.display.set_mode([self.window_width, self.window_height])

        # Store configurations
        self.tello_configs = tello_configs

        # Init Tello objects
        self.tellos: Dict[str, Tello] = {}
        self.video_streams: Dict[str, VideoStreamHandler] = {}
        self.video_ports = {}
        for ip, port in tello_configs:
            self.tellos[ip] = Tello(ip)
            self.video_ports[ip] = port

        # Drone velocities between -100~100
        self.velocities = {}
        for ip, _ in tello_configs:
            self.velocities[ip] = {
                'for_back_velocity': 0,
                'left_right_velocity': 0,
                'up_down_velocity': 0,
                'yaw_velocity': 0
            }

        self.speed = 10
        self.send_rc_control = {}
        for ip, _ in tello_configs:
            self.send_rc_control[ip] = False

        # Selected drone for control (initially first drone)
        self.selected_drone = tello_configs[0][0]
        
        # Font for rendering text
        pygame.font.init()
        self.font = pygame.font.Font(None, 36)

        # Create update timer
        pygame.time.set_timer(pygame.USEREVENT + 1, 1000 // FPS)

    def connect_tellos(self):
        """Connect to all Tello drones and start their video streams"""
        for ip, tello in self.tellos.items():
            try:
                print(f"Connecting to Tello at {ip}...")
                port = self.video_ports[ip]
                
                # Connect and configure Tello
                tello.connect()
                tello.set_speed(self.speed)
                
                # Configure video stream
                tello.streamoff()
                time.sleep(0.5)
                # tello.set_video_port(port)
                # time.sleep(0.5)
                tello.streamon()
                time.sleep(0.5)
                
                # Initialize video stream handler
                stream_handler = VideoStreamHandler(tello, port)
                stream_handler.start()
                self.video_streams[ip] = stream_handler
                
                print(f"Successfully connected to Tello at {ip} with video port {port}")
                
            except Exception as e:
                print(f"Failed to connect to Tello at {ip}: {str(e)}")

    def get_frame_surface(self, frame):
        """Convert frame to pygame surface"""
        frame = np.rot90(frame)
        frame = np.flipud(frame)
        frame = pygame.surfarray.make_surface(frame)
        return frame

    def draw_drone_info(self, frame, ip, battery):
        """Draw drone information on frame"""
        text = f"IP: {ip} | Port: {self.video_ports[ip]} | Bat: {battery}% | {'SELECTED' if ip == self.selected_drone else ''}"
        cv2.putText(frame, text, (5, 720 - 5),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 255), 2)
        return frame

    def get_frame_position(self, index):
        """Calculate frame position in the window based on index"""
        col = index % self.cols
        row = index // self.cols
        x = col * 960
        y = row * 720
        return x, y

    def keydown(self, key):
        """Update velocities based on key pressed"""
        if key == pygame.K_UP:
            self.velocities[self.selected_drone]['for_back_velocity'] = S
        elif key == pygame.K_DOWN:
            self.velocities[self.selected_drone]['for_back_velocity'] = -S
        elif key == pygame.K_LEFT:
            self.velocities[self.selected_drone]['left_right_velocity'] = -S
        elif key == pygame.K_RIGHT:
            self.velocities[self.selected_drone]['left_right_velocity'] = S
        elif key == pygame.K_w:
            self.velocities[self.selected_drone]['up_down_velocity'] = S
        elif key == pygame.K_s:
            self.velocities[self.selected_drone]['up_down_velocity'] = -S
        elif key == pygame.K_a:
            self.velocities[self.selected_drone]['yaw_velocity'] = -S
        elif key == pygame.K_d:
            self.velocities[self.selected_drone]['yaw_velocity'] = S

    def keyup(self, key):
        """Update velocities based on key released"""
        if key == pygame.K_UP or key == pygame.K_DOWN:
            self.velocities[self.selected_drone]['for_back_velocity'] = 0
        elif key == pygame.K_LEFT or key == pygame.K_RIGHT:
            self.velocities[self.selected_drone]['left_right_velocity'] = 0
        elif key == pygame.K_w or key == pygame.K_s:
            self.velocities[self.selected_drone]['up_down_velocity'] = 0
        elif key == pygame.K_a or key == pygame.K_d:
            self.velocities[self.selected_drone]['yaw_velocity'] = 0
        elif key == pygame.K_t:  # takeoff
            print(f"Takeoff command for Tello at {self.selected_drone}")
            self.tellos[self.selected_drone].takeoff()
            self.send_rc_control[self.selected_drone] = True
        elif key == pygame.K_l:  # land
            print(f"Land command for Tello at {self.selected_drone}")
            self.tellos[self.selected_drone].land()
            self.send_rc_control[self.selected_drone] = False

    def update(self):
        """Update routine. Send velocities to selected Tello."""
        if self.selected_drone in self.send_rc_control and self.send_rc_control[self.selected_drone]:
            vel = self.velocities[self.selected_drone]
            self.tellos[self.selected_drone].send_rc_control(
                vel['left_right_velocity'],
                vel['for_back_velocity'],
                vel['up_down_velocity'],
                vel['yaw_velocity']
            )

    def cleanup(self):
        """Clean up resources"""
        for ip in self.tellos.keys():
            try:
                if ip in self.video_streams:
                    self.video_streams[ip].stop()
                    
                print(f"Cleaning up resources for Tello at {ip}")
                if self.send_rc_control[ip]:
                    self.tellos[ip].land()
                self.tellos[ip].streamoff()
                self.tellos[ip].end()
            except Exception as e:
                print(f"Error during cleanup for Tello at {ip}: {str(e)}")

    def run(self):
        """Main run loop"""
        print("Connecting to Tellos...")
        self.connect_tellos()
        print("Starting main loop...")
        should_stop = False

        while not should_stop:
            for event in pygame.event.get():
                if event.type == pygame.USEREVENT + 1:
                    self.update()
                elif event.type == pygame.QUIT:
                    should_stop = True
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        should_stop = True
                    elif event.key in [pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4]:
                        drone_index = event.key - pygame.K_1
                        if drone_index < len(self.tellos):
                            self.selected_drone = list(self.tellos.keys())[drone_index]
                            print(f"Selected drone: {self.selected_drone}")
                    else:
                        self.keydown(event.key)
                elif event.type == pygame.KEYUP:
                    self.keyup(event.key)

            # Fill background
            self.screen.fill((0, 0, 0))

            # Update and display each drone's frame
            for i, (ip, stream_handler) in enumerate(self.video_streams.items()):
                if stream_handler.stopped:
                    continue

                frame = stream_handler.get_frame()
                if frame is not None:
                    try:
                        battery = self.tellos[ip].get_battery()
                    except:
                        battery = 0
                    
                    frame = self.draw_drone_info(frame, ip, battery)
                    frame_surface = self.get_frame_surface(frame)
                    x, y = self.get_frame_position(i)
                    self.screen.blit(frame_surface, (x, y))

            pygame.display.update()
            time.sleep(1 / FPS)

        print("Cleaning up...")
        self.cleanup()

def main():
    # Example usage with multiple drones and custom ports
    tello_configs = [
        ("192.168.10.1", 11111),  # Tello 1: IP and video port
        ("192.168.3.21", 11118),  # Tello 2: IP and video port
    ]
    
    frontend = MultiTelloFrontEnd(tello_configs)
    frontend.run()

if __name__ == '__main__':
    main()