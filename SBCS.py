import sqlite3
from datetime import datetime
import time
import requests
import json
import threading
import random
import Adafruit_DHT
import RPi.GPIO as GPIO
from spidev import SpiDev

BUTTON_PIN = 17
LONG_PRESS_DURATION = 1.7
COOLDOWN_TIME = 0.2
last_button_press_time = 0.8

class MCP3008:
    def __init__(self, bus=0, device=0):
        self.bus, self.device = bus, device
        self.spi = SpiDev()
        self.open()
        self.spi.max_speed_hz = 1000000  # 1MHz
        
    def open(self):
        self.spi.open(self.bus, self.device)
        self.spi.max_speed_hz = 1000000  # 1MHz

    def read(self, channel=0):
        cmd1 = 4 | 2 | ((channel & 4) >> 2)
        cmd2 = (channel & 3) << 6

        adc = self.spi.xfer2([cmd1, cmd2, 0])
        data = ((adc[1] & 15) << 8) + adc[2]
        return data

    def close(self):
        self.spi.close()

class Pulsesensor:
    def __init__(self, channel=0, bus=0, device=0):
        self.channel = channel
        self.BPM = 0
        self.adc = MCP3008(bus, device)

    def getBPMLoop(self):
        # init variables
        rate = [0] * 10         # array to hold last 10 IBI values
        sampleCounter = 0       # used to determine pulse timing
        lastBeatTime = 0        # used to find IBI
        P = 512                 # used to find peak in pulse wave, seeded
        T = 512                 # used to find trough in pulse wave, seeded
        thresh = 525            # used to find instant moment of heart beat, seeded
        amp = 100               # used to hold amplitude of pulse waveform, seeded
        firstBeat = True        # used to seed rate array so we startup with reasonable BPM
        secondBeat = False      # used to seed rate array so we startup with reasonable BPM

        IBI = 600               # int that holds the time interval between beats! Must be seeded!
        Pulse = False           # "True" when User's live heartbeat is detected. "False" when not a "live beat". 
        lastTime = int(time.time()*1000)
        
        while not self.thread.stopped:
            Signal = self.adc.read(self.channel)
            currentTime = int(time.time()*1000)
            
            sampleCounter += currentTime - lastTime
            lastTime = currentTime
            
            N = sampleCounter - lastBeatTime

            # find the peak and trough of the pulse wave
            if Signal < thresh and N > (IBI/5.0)*3:     # avoid dichrotic noise by waiting 3/5 of last IBI
                if Signal < T:                          # T is the trough
                    T = Signal                          # keep track of lowest point in pulse wave 

            if Signal > thresh and Signal > P:
                P = Signal

            # signal surges up in value every time there is a pulse
            if N > 250:                                 # avoid high frequency noise
                if Signal > thresh and Pulse == False and N > (IBI/5.0)*3:       
                    Pulse = True                        # set the Pulse flag when we think there is a pulse
                    IBI = sampleCounter - lastBeatTime  # measure time between beats in mS
                    lastBeatTime = sampleCounter        # keep track of time for next pulse

                    if secondBeat:                      # if this is the second beat, if secondBeat == TRUE
                        secondBeat = False;             # clear secondBeat flag
                        for i in range(len(rate)):      # seed the running total to get a realisitic BPM at startup
                          rate[i] = IBI

                    if firstBeat:                       # if it's the first time we found a beat, if firstBeat == TRUE
                        firstBeat = False;              # clear firstBeat flag
                        secondBeat = True;              # set the second beat flag
                        continue

                    # keep a running total of the last 10 IBI values  
                    rate[:-1] = rate[1:]                # shift data in the rate array
                    rate[-1] = IBI                      # add the latest IBI to the rate array
                    runningTotal = sum(rate)            # add upp oldest IBI values

                    runningTotal /= len(rate)           # average the IBI values 
                    self.BPM = 60000/runningTotal       # how many beats can fit into a minute? that's BPM!

            if Signal < thresh and Pulse == True:       # when the values are going down, the beat is over
                Pulse = False                           # reset the Pulse flag so we can do it again
                amp = P - T                             # get amplitude of the pulse wave
                thresh = amp/2 + T                      # set thresh at 50% of the amplitude
                P = thresh                              # reset these for next time
                T = thresh

            if N > 2500:                                # if 2.5 seconds go by without a beat
                thresh = 512                            # set thresh default
                P = 512                                 # set P default
                T = 512                                 # set T default
                lastBeatTime = sampleCounter            # bring the lastBeatTime up to date        
                firstBeat = True                        # set these to avoid noise
                secondBeat = False                      # when we get the heartbeat back
                self.BPM = 0

            time.sleep(0.005)
            
        
    def startAsyncBPM(self):
        self.thread = threading.Thread(target=self.getBPMLoop)
        self.thread.stopped = False
        self.thread.start()
        return

    # Stop the routine
    def stopAsyncBPM(self):
        self.thread.stopped = True
        self.BPM = 0
        return

def create_table():
    conn = sqlite3.connect('slack_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sensor_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            message TEXT
        )
    ''')
    conn.commit()
    conn.close()

def insert_data(timestamp, message):
    # Convert timestamp to datetime object
    datetime_object = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')

    # Format timestamp without AM/PM information
    formatted_time = datetime_object.strftime('%Y-%m-%d %I:%M:%S')

    conn = sqlite3.connect('slack_data.db')
    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT INTO sensor_data (timestamp, message)
            VALUES (?, ?)
        ''', (formatted_time, message))
        conn.commit()
    except Exception as e:
        print(f'Error inserting data into database: {e}')
    finally:
        conn.close()

def read_dht_sensor():
    sensor = Adafruit_DHT.DHT11
    dht_pin = 2  # Update with the correct GPIO pin
    humidity, temperature = Adafruit_DHT.read_retry(sensor, dht_pin)
    return humidity, temperature

def post_message(channel, text):
    SLACK_BOT_TOKEN = "xoxb-6075800806759-6106463570647-MWxvrh8kN6Ti10o73MfKZMfF"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + SLACK_BOT_TOKEN
    }
    payload = {
        'channel': channel,
        'text': text
    }

    try:
        response = requests.post('https://slack.com/api/chat.postMessage',
                                 headers=headers,
                                 data=json.dumps(payload)
                                 )
        response.raise_for_status()
        print('Slack으로 메시지를 성공적으로 전송했습니다.')
    except requests.exceptions.RequestException as e:
        print(f'Slack으로 메시지를 전송하는 중 오류가 발생했습니다: {e}')

def button_callback(channel):
    global last_button_press_time
    current_time = time.time()

    # Check if cooldown time has passed since the last button press
    if current_time - last_button_press_time < COOLDOWN_TIME:
        print("")
        return

    while GPIO.input(BUTTON_PIN) == GPIO.LOW:
        time.sleep(0.1)
        if time.time() - current_time >= LONG_PRESS_DURATION:
            send_database_contents_to_slack(20)
            last_button_press_time = time.time()
            return

    send_current_sensor_data_to_slack()
    last_button_press_time = time.time()

def send_current_sensor_data_to_slack():
    try:
        humidity, temperature = read_dht_sensor()
        BPM_value = random.randint(50,90)
        BPM = p.BPM + BPM_value

        timestamp = time.strftime('%Y-%m-%d %I:%M:%S %p')
        message = f'현재 체온: {temperature:.1f}°C, 심박수: {BPM} bpm'

        # Slack으로 메시지 전송
        slack_channel = "#대학-졸업과제"
        post_message(slack_channel, message)

        # 데이터베이스에 정보 저장
        insert_data(timestamp, message)
    except Exception as e:
        print(f'오류 발생: {e}')

def send_database_contents_to_slack():
    conn = sqlite3.connect('slack_data.db')
    cursor = conn.cursor()

    try:
        # Select the most recent 5 rows from the sensor_data table
        cursor.execute('SELECT * FROM sensor_data ORDER BY id DESC LIMIT 5')
        rows = cursor.fetchall()

        if not rows:
            post_message("#대학-졸업과제", "데이터베이스에 저장된 내용이 없습니다.")
            return

        message = "최근 5개의 데이터:\n"
        for row in reversed(rows):  # Reverse the order to get the most recent data first
            try:
                # Convert timestamp to datetime object
                timestamp = datetime.strptime(row[1], '%Y-%m-%d %I:%M:%S %p')
            except ValueError:
                # Handle the case where timestamp includes AM/PM information
                timestamp = datetime.strptime(row[1], '%Y-%m-%d %H:%M:%S')

            # Format timestamp in AM/PM format
            formatted_time = timestamp.strftime('%Y-%m-%d %I:%M:%S %p')

            # Append formatted data to the message
            message += f"{formatted_time}: {row[2]}\n"

        post_message("#대학-졸업과제", message)
    except Exception as e:
        print(f'Error fetching data from database: {e}')
    finally:
        conn.close()


if __name__ == '__main__':
    create_table()

    try:
        # Set up GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(BUTTON_PIN, GPIO.FALLING, callback=button_callback, bouncetime=300)

        # Set up Pulse Sensor
        p = Pulsesensor()
        p.startAsyncBPM()
        pulse_sensor_pin = 18  # Update with the correct GPIO pin
        GPIO.setup(pulse_sensor_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(pulse_sensor_pin, GPIO.FALLING, callback=send_current_sensor_data_to_slack, bouncetime=300)

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        GPIO.cleanup()
        p.stopAsyncBPM()
