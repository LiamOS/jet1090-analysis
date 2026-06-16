import sys
import json
import time
from PyQt6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt, QTimer
import threading

# Dictionary to hold information about each ICAO24 code
icao_info = {}

class IcaoInfoWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ICAO Code Information")
        self.resize(1440, 1024)

        # Set up the table widget and layout
        self.table_widget = QTableWidget()
        self.table_widget.setColumnCount(11)
        self.table_widget.setHorizontalHeaderLabels([
            "ICAO", "DAQ", "Count", "Earliest T",
            "Latest T", "Track", "Altitude",
            "Vertical Rate", "Ground Spd",
            "Latitude", "Longitude"
        ])

        layout = QVBoxLayout()
        layout.addWidget(self.table_widget)
        self.setLayout(layout)

    def update_table(self):
        # Clear the table
        self.table_widget.setRowCount(0)

        # Sort by has_lat_lon first (True before False), then sort by count in descending order
        sorted_icaos = sorted(
            icao_info.items(),
            key=lambda item: (
                not item[1]['has_lat_lon'],  # Put items with lat/lon first (not True comes before not False)
                -item[1]['count']           # Then sort by count in descending order
            )
        )

        # Add rows for each ICAO code
        for icao_code, info in sorted_icaos:
            row_count = self.table_widget.rowCount()
            self.table_widget.insertRow(row_count)
            items = [
                QTableWidgetItem(str(info['has_lat_lon'])),
                QTableWidgetItem(str(info['count'])),
                QTableWidgetItem(str(info['earliest_timestamp'])),
                QTableWidgetItem(str(info['latest_timestamp']))
            ]
            for param in ['track', 'altitude', 'vertical_rate', 'groundspeed', 'latitude', 'longitude']:
                if info[param]:
                    latest_value = info[param][-1] if len(info[param]) > 0 else None
                    items.append(QTableWidgetItem(str(latest_value)))
                else:
                    items.append(QTableWidgetItem(""))

            self.table_widget.setItem(row_count, 0, QTableWidgetItem(icao_code))
            for col, item in enumerate(items):
                self.table_widget.setItem(row_count, col + 1, item)

def process_line(line):
    try:
        # Parse JSON data from line
        data = json.loads(line)

        # Check if 'icao24' and 'timestamp' keys are in the parsed JSON data
        if 'icao24' not in data or 'timestamp' not in data:
            return

        icao_code = data['icao24']
        timestamp = data['timestamp']

        current_time = time.time()

        # Initialize information for this ICAO code if it doesn't exist yet
        if icao_code not in icao_info:
            icao_info[icao_code] = {
                'count': 0,
                'has_lat_lon': False,  # New parameter to track lat/lon data
                'earliest_timestamp': None,
                'latest_timestamp': None,
                'last_seen': current_time,  # Track when this ICAO code was last updated
                'track': [],
                'altitude': [],
                'vertical_rate': [],
                'latitude': [],
                'longitude': [],
                'groundspeed': []
            }

        # Update the count and timestamps
        icao_info[icao_code]['count'] += 1

        if icao_info[icao_code]['earliest_timestamp'] is None or timestamp < icao_info[icao_code]['earliest_timestamp']:
            icao_info[icao_code]['earliest_timestamp'] = timestamp
        if icao_info[icao_code]['latest_timestamp'] is None or timestamp > icao_info[icao_code]['latest_timestamp']:
            icao_info[icao_code]['latest_timestamp'] = timestamp

        # Update additional parameters and check for lat/lon data
        has_lat_lon = False
        for param in ['track', 'altitude', 'latitude', 'longitude', 'vertical_rate', 'groundspeed']:
            if param in data:
                icao_info[icao_code][param].append(data[param])
                # Check specifically for latitude and longitude
                if param == 'latitude' or param == 'longitude':
                    has_lat_lon = True
                    icao_info[icao_code]['has_lat_lon'] = has_lat_lon # do in here so we don't overwrite True with False

        # Update the last seen time for this ICAO code
        icao_info[icao_code]['last_seen'] = current_time

    except json.JSONDecodeError as e:
        print(f"Warning: Failed to parse JSON line. Error: {e}")

def clean_expired_icaos():
    """Remove ICAOs that have not been seen in the last 100 seconds"""
    global icao_info
    current_time = time.time()
    expired_icaos = [icao for icao, info in icao_info.items() if (current_time - info['last_seen']) > 100]

    for expired_icao in expired_icaos:
        del icao_info[expired_icao]

def read_lines_from_stdin():
    while True:
        line = sys.stdin.readline()
        if not line:  # EOF
            break
        process_line(line.strip())

def main():
    app = QApplication(sys.argv)
    window = IcaoInfoWindow()
    window.show()

    # Start a separate thread to read lines from stdin
    stdin_thread = threading.Thread(target=read_lines_from_stdin, daemon=True)
    stdin_thread.start()

    # Use a timer to periodically update the table and clean expired ICAOs
    timer = QTimer()
    timer.timeout.connect(lambda: (clean_expired_icaos(), window.update_table()))
    timer.start(1000)  # Update every second

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
