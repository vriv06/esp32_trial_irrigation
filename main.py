import time
import logging
from machine import Pin, I2C
from secrets import DEVICE_ID, CLOUD_PASSWORD
from arduino_iot_cloud import Task, ArduinoCloudClient, async_wifi_connection

# I2C address of the AM2315
AM2315_I2C_ADDRESS = 0x5C

# Initialize I2C
i2c = I2C(0, scl=Pin(12), sda=Pin(11), freq=10000)
relay = Pin(14, Pin.OUT)

# Global variables for irrigation
irrigation_day = 0
irr_passed = 0
relay.value(0)
irrigation_interval = 0
intervals_done = 0
irrigate = False


def wdt_task(client):
    global wdt
    wdt.feed()

def wake_up_sensor():
    try:
        i2c.writeto(AM2315_I2C_ADDRESS, b'\x00')
        time.sleep(0.1)
    except OSError:
        pass

def read_data():
    for attempt in range(3):  # Retry up to 3 times
        try:
            wake_up_sensor()
            # Send read command
            i2c.writeto(AM2315_I2C_ADDRESS, b'\x03\x00\x04')
            time.sleep(0.2)  # Increased read delay
            # Read 8 bytes of data
            data = i2c.readfrom(AM2315_I2C_ADDRESS, 8)
            if len(data) == 8 and data[0] == 0x03 and data[1] == 0x04:
                humidity = (data[2] << 8 | data[3]) / 10.0
                temperature = (data[4] << 8 | data[5]) / 10.0
                return temperature, humidity
            else:
                print(f"Invalid data received, attempt {attempt + 1}")
        except OSError as e:
            print(f"Error reading AM2315 on attempt {attempt + 1}: {e}")
        time.sleep(0.5 * (attempt + 1))  # Exponential back-off
    return None, None

def read_temperature(client):
    temperature, _ = read_data()
    print('Temperature: {} C'.format(temperature))
    return temperature if temperature is not None else 1000.0

def read_humidity(client):
    _, humidity = read_data()
    print('Humidity: {} %'.format(humidity))
    return humidity if humidity is not None else -1000.0

def read_relay_state(client):
    state = relay.value()
    return bool(state)


def on_irrigation_day_changed(client, value):
    global irrigation_day, irr_passed, irrigation_interval, irrigate, intervals_done
    irrigation_day = float(value)
    irrigation_interval = irrigation_day / 14
    #client["irrigation_day"] = irrigation_day
    print('Updated values from the cloud')
    print('Irrigation of the day: {} min'.format(irrigation_day))
    print("Irrigation interval: {}".format(irrigation_interval))
    if irrigation_day > 0:
        irrigate = True
    else:
        irrigate = False
        
def get_intervals_done(client, value):
    global intervals_done
    intervals_done = float(value)
    #client["irrigation_day"] = irrigation_day
    print('Updated values from the cloud')
    print("Hours of irrigation made: {} hours".format(intervals_done))

def irrigation_task(client):
    global irr_passed, irrigate, irrigation_day, intervals_done
    if irrigation_day > 0:
        relay.value(1)
        client["relay"] = True
        print("Relay is ON and updated to cloud")
        time.sleep(irrigation_interval * 60)
        relay.value(0)
        client["relay"] = False
        print("Relay is OFF and updated to cloud")
        
        irr_passed = irr_passed + irrigation_interval
        intervals_done = intervals_done + 1
        print("Amount of irrigations made: {}".format(intervals_done))
        print("Minutes of irrigation made so far: {}".format(irr_passed))
        client["intervals_done"] = intervals_done
        if intervals_done >= 14:
            irrigation_day = 0
            intervals_done = 0
            irr_passed = 0
            #irrigate = False
            client["irrigation_day"] = irrigation_day
            client["intervals_done"] = intervals_done
            print("Irrigation of the day completed")
            
        print('Irrigation remaining: {} min'.format(irrigation_day - irr_passed))
    else:
        print('no irrigation this hour')

def fetch_irrigation_values(client):
    global irrigation_day, irr_passed, irrigate
    try:
        # Attempt to fetch the values from the cloud
        #cloud_irrigation_day = client.get("irrigation_day", None)
        cloud_irr_passed = client.get("irr_passed", None)
        
        # Use fetched values if they exist, otherwise fall back to local variables
        #if cloud_irrigation_day is not None:
            #irrigation_day = cloud_irrigation_day
        if cloud_irr_passed > 0:
            irr_passed = cloud_irr_passed
            irrigate = True

        
    except Exception as e:
        # In case of any exception, log the error and fall back to local values
        print(f"Failed to fetch values from cloud: {e}")
        print(f"Using local values: irrigation_day={irrigation_day}, irr_passed={irr_passed}")

#async def main():
if __name__ == "__main__":
    logging.basicConfig(
        datefmt="%H:%M:%S",
        format="%(asctime)s.%(msecs)03d %(message)s",
        level=logging.INFO,
    )

    client = ArduinoCloudClient(
        device_id=DEVICE_ID, username=DEVICE_ID, password=CLOUD_PASSWORD
    )
    
    client.register("relay", value=None, on_read=read_relay_state, interval=0.1)
    client.register("intervals_done", value=None, on_write=get_intervals_done)
    client.register("irrigation_day", value=None, on_write=on_irrigation_day_changed)
    client.register("humidity", value=None, on_read=read_humidity, interval=55.0)
    client.register("temperature", value=None, on_read=read_temperature, interval=60.0)
    client.register(Task("irrigation_task", on_run=irrigation_task, interval=3600))  # Run every hour
    # Register the Wi-Fi connection task
    client.register(Task("wifi_connection", on_run=async_wifi_connection, interval=60.0))

    if True:
        try:
            from machine import WDT
            # Enable the WDT with a timeout of 5s (1s is the minimum)
            wdt = WDT(timeout=7500)
            client.register(Task("watchdog_task", on_run=wdt_task, interval=1.0))
        except (ImportError, AttributeError):
            pass

    #await client.start()
    client.start()

    #fetch_irrigation_values(client)

    while True:
        client.update()
        time.sleep(0.100)

# Start the main async function
#import uasyncio as asyncio
#try:
#    asyncio.run(main())
#except Exception as e:
#    print(f"Unhandled exception: {e}")