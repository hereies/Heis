from flask import Flask, render_template, request
import json

app = Flask(__name__)

sensor_data = {"temperature": None, "humidity": None}


@app.route('/')
def index():
    return render_template('index.html', sensor_data=sensor_data)


@app.route('/update', methods=['POST'])
def update_sensor_data():
    global sensor_data
    data = request.get_json()
    sensor_data['temperature'] = data['temperature']
    sensor_data['humidity'] = data['humidity']
    return json.dumps({'success': True}), 200, {'ContentType': 'application/json'}


if __name__ == '__main__':
    app.run(debug=True)
