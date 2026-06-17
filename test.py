import sys
import json
import time
from PyQt6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHBoxLayout
from PyQt6.QtCore import Qt, QTimer
import threading
import numpy as np

# For matplotlib plot
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# Radius of Earth in km
R_EARTH = 6371
STATION_LAT = 50.011
STATION_LON = 8.265
STATION_ALT = 200 # feet

# Dictionary to hold information about each ICAO24 code
icao_info = {}

class MatplotlibWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)

        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        self.setLayout(layout)

        # Set up the plot
        self.axes = self.figure.add_subplot(111)
        self.axes.set_xlim([0, 360])
        self.axes.set_ylim([0, 90])
        self.axes.set_xlabel('Bearing')
        self.axes.set_ylabel('Elevation')

    def update_plot(self):
        """Clear the plot and draw new points"""
        self.axes.clear()
        self.axes.set_xlim([0, 360])
        self.axes.set_ylim([0, 90])
        self.axes.set_xlabel('Bearing')
        self.axes.set_ylabel('Elevation')

        # Plot data for each ICAO code that has lat/lon
        for icao_code, info in icao_info.items():
            if info['has_lat_lon']:
                if len(info['bearing']) > 0 and len(info['elevation']) > 0:
                    self.axes.scatter(
                        [info['bearing'][-1]],
                        [info['elevation'][-1]],
                        label=icao_code
                    )

        # Only show legend for the last point to avoid clutter
        handles, labels = self.axes.get_legend_handles_labels()
        unique_labels = dict(zip(labels, handles))
        self.axes.legend(unique_labels.values(), unique_labels.keys())

        self.canvas.draw()

class IcaoInfoWindow(QWidget):
    def __init__(self):
        super().__init__()

        # Create the main layout
        main_layout = QVBoxLayout(self)
        self.setWindowTitle("ADSB Tracks")
        self.resize(1600,1000)

        # Table widget
        self.table_widget = QTableWidget()
        main_layout.addWidget(self.table_widget)

        # Matplotlib plot widget
        self.plot_widget = MatplotlibWidget()
        main_layout.addWidget(self.plot_widget)

    def update_table(self):
        """Update the table with data from icao_info"""
        # Clear the current table content
        #self.table_widget.clearContents()
        self.table_widget.setRowCount(0)

        # Sort by has_lat_lon first (True before False), then sort by count in descending order
        sorted_icaos = sorted(
            icao_info.items(),
            key=lambda item: (
                not item[1]['has_lat_lon'],  # Put items with lat/lon first (not True comes before not False)
                -item[1]['count']           # Then sort by count in descending order
            )
        )

        # Set the rows and columns based on icao_info
        #self.table_widget.setRowCount(len(icao_info))
        self.table_widget.setColumnCount(15)
        self.table_widget.setHorizontalHeaderLabels([
            "ICAO", "DAQ", "Count", "Earliest T",
            "Latest T", "Track", "Altitude",
            "Vertical Rate", "Ground Spd",
            "Latitude", "Longitude", "Bearing",
            "Elevation", "Distance", "LOS"
        ])


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
            for param in ['track', 'altitude', 'vertical_rate', 'groundspeed', 'latitude', 'longitude', 'bearing', 'elevation', 'distance', 'los']:
                if info[param]:
                    latest_value = info[param][-1] if len(info[param]) > 0 else None
                    items.append(QTableWidgetItem(str(latest_value)))
                else:
                    items.append(QTableWidgetItem(""))

            self.table_widget.setItem(row_count, 0, QTableWidgetItem(icao_code))
            for col, item in enumerate(items):
                self.table_widget.setItem(row_count, col + 1, item)

        # Update the plot
        self.plot_widget.update_plot()

def haversine(lat1, lon1, lat2, lon2):
    lat1r = lat1*0.0174533 # in radians
    lon1r = lon1*0.0174533
    lat2r = lat2*0.0174533
    lon2r = lon2*0.0174533
    dlat = (lat1r-lat2r) # difference between target and station latitudes [radian]
    dlon = (lon1r-lon2r)

    a = np.sin(dlat/2)**2 + np.cos(lat1r)*np.cos(lat2r)*(np.sin(dlon/2)**2)
    c = 2*np.atan2(np.sqrt(a), np.sqrt(1-a))
    return c

def lineofsight(lat1, lon1, lat2, lon2, alt, elev):
    alt /= 3282.8 # convert to km
    c = haversine(lat1,lon1,lat2,lon2)
    return (R_EARTH + alt)*np.sin(c)/np.sin(np.pi/2 + elev*0.0174533) # [km]

def bearing(lat1, lon1, lat2, lon2):
    lat1r = lat1*0.0174533
    lon1r = lon1*0.0174533
    lat2r = lat2*0.0174533
    lon2r = lon2*0.0174533

    dlon = (lon2r-lon1r)
    theta = np.atan2(np.sin(dlon)*np.cos(lat2r), np.cos(lat1r)*np.sin(lat2r) - np.sin(lat1r)*np.cos(lat2r)*np.cos(dlon))
    return np.fmod(180*theta/np.pi + 360,360)

def elevation(alt, dist):
    if (dist == 0.0):
        return 90.0
    alt = alt/3.2828 # convert to km
    return np.atan2(alt, dist*1000)/0.0174533

def process_line(line):
    try:
        data = json.loads(line)
        if 'icao24' not in data or 'timestamp' not in data:
            return

        icao_code = data['icao24']
        timestamp = data['timestamp']

        current_time = time.time()

        if icao_code not in icao_info:
            icao_info[icao_code] = {
                'count': 0,
                'has_lat_lon': False,
                'earliest_timestamp': None,
                'latest_timestamp': None,
                'last_seen': current_time,
                'track': [],
                'altitude': [],
                'vertical_rate': [],
                'latitude': [],
                'longitude': [],
                'groundspeed': [],
                'bearing': [],
                'elevation': [],
                'distance': [],
                'los': []
            }

        icao_info[icao_code]['count'] += 1

        if icao_info[icao_code]['earliest_timestamp'] is None or timestamp < icao_info[icao_code]['earliest_timestamp']:
            icao_info[icao_code]['earliest_timestamp'] = timestamp
        if icao_info[icao_code]['latest_timestamp'] is None or timestamp > icao_info[icao_code]['latest_timestamp']:
            icao_info[icao_code]['latest_timestamp'] = timestamp

        has_lat_lon = False
        for param in ['track', 'altitude', 'latitude', 'longitude', 'vertical_rate', 'groundspeed']:
            if param in data:
                icao_info[icao_code][param].append(data[param])
                if param == 'latitude' or param == 'longitude':
                    has_lat_lon = True
                    icao_info[icao_code]['has_lat_lon'] = has_lat_lon

        if has_lat_lon:
            icao_info[icao_code]['distance'].append(R_EARTH*haversine(STATION_LAT, STATION_LON, icao_info[icao_code]['latitude'][-1], icao_info[icao_code]['longitude'][-1]))
            icao_info[icao_code]['bearing'].append(bearing(STATION_LAT, STATION_LON, icao_info[icao_code]['latitude'][-1], icao_info[icao_code]['longitude'][-1]))
            icao_info[icao_code]['elevation'].append(elevation(icao_info[icao_code]['altitude'][-1],icao_info[icao_code]['distance'][-1]))
            icao_info[icao_code]['los'].append(lineofsight(STATION_LAT, STATION_LON, icao_info[icao_code]['latitude'][-1], icao_info[icao_code]['longitude'][-1],
icao_info[icao_code]['altitude'][-1], icao_info[icao_code]['elevation'][-1]))

        icao_info[icao_code]['last_seen'] = current_time

    except json.JSONDecodeError as e:
        print(f"Warning: Failed to parse JSON line. Error: {e}")

def clean_expired_icaos():
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
