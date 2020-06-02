import os, json
import timetable, facebook
from pymongo import MongoClient
from flask_wtf import FlaskForm
from cryptography.fernet import Fernet
from wtforms.validators import DataRequired
from wtforms import StringField, PasswordField, SubmitField, HiddenField
from flask import Flask, request, redirect, render_template, make_response


app = Flask(__name__)
app_url = os.environ["APP_URL"]
app.config['SECRET_KEY'] = os.environ["FLASK_KEY"]
PAGE_ACCESS_TOKEN = os.environ["PAGE_ACCESS_TOKEN"]
webhook_token = os.environ["VERIFY_TOKEN"]
wb_arg_name = os.environ["WB_ARG_NAME"]
cluster = MongoClient(os.environ["MONGO_TOKEN"])
db = cluster[os.environ["FIRST_CLUSTER"]]
collection = db[os.environ["COLLECTION_NAME"]]
wait_id = os.environ["WAIT_ID"]
f = Fernet(os.environ["FERNET_KEY"])


class RegisterForm(FlaskForm):
    fb_id = HiddenField('fb_id')
    uni_id = StringField('University ID', validators=[DataRequired()])
    uni_pass = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/webhook', methods=['POST'])
def webhook():

    if not request.headers.get(wb_arg_name) == webhook_token:
        return "Verification token mismatch", 403

    data = request.get_json()

    # This area is a little delicate due to Dialogflow. WIP
    try: sender_id = data['originalDetectIntentRequest']['payload']['data']['sender']['id']
    except KeyError: return
    
    if collection.count_documents({"_id": sender_id}) > 0:
        response = parse_message(data, sender_id)

    elif collection.count_documents({"_id": wait_id+sender_id}) > 0:
        response = ("It doesn't seem like you've registered yet.\n"
                    "Register here: {}/register?key={}").format(app_url, sender_id)
    
    else:
        user_data = facebook.get_user_data(sender_id, PAGE_ACCESS_TOKEN)
        if 'error' in user_data:
            log("{} is not a valid Facebook user".format(sender_id))
            return
        collection.insert_one({"_id": wait_id+sender_id})
        response = ("Hey there, {}! I'm Boyd Bot - your university chatbot, here to make things easier. "
                    "To get started, register here: {}/register?key={}").format(user_data['first_name'], app_url, sender_id)

    return prepare_json(response)


@app.route('/register', methods=['GET', 'POST'])
def new_user_registration():

    if request.method == 'GET':
        pk = request.args.get('key')
        return render_template('register.html', form=RegisterForm(fb_id=pk), message="") \
            if collection.count_documents({"_id": wait_id+str(pk)}) > 0 else redirect('/')
    
    else:
        fb_id = request.form.get('fb_id')
        uni_id = request.form.get('uni_id')
        uni_pass = request.form.get('uni_pass')
        login_result = timetable.login(uni_id, uni_pass)
        log("{} undergoing registration. Result: {}".format(fb_id, login_result))

        if not login_result:
            form = RegisterForm(fb_id=fb_id)
            return render_template('register.html', form=form, message="Invalid credentials.")
        
        collection.insert_one({"_id": fb_id, "uni_id": uni_id, "uni_pw": f.encrypt(uni_pass.encode())})
        collection.delete_one({"_id": wait_id+fb_id})
        facebook.send_message(fb_id, PAGE_ACCESS_TOKEN, "Alrighty! We can get started. :D")
        return render_template('register.html', success='Login successful! You can now close this page and chat to the bot.')


def prepare_json(message):

    res = { 'fulfillmentText': message, }
    res = json.dumps(res, indent=4)
    r = make_response(res)
    r.headers['Content-Type'] = 'application/json'
    return r


def handle_intent(data, r):

    intent = data['queryResult']['intent']
    
    try:

        if 'displayName' not in intent:
            return

        if intent['displayName'].lower() == 'delete data':
            collection.delete_one({"_id": r['_id']})
            return "Deleted! :) "

        elif intent['displayName'].lower() == 'read next':
            return timetable.read_schedule(r['uni_id'])
        
        elif intent['displayName'].lower() == 'read timetable':

            param = data['queryResult']['parameters']['date-time']
            # looks like a bunch of if-else statements; this is WIP
            if 'date_time' in param:
                return timetable.read_schedule(r['uni_id'], param['date_time'])
            elif 'startDateTime' in param:
                return timetable.read_schedule(r['uni_id'], param['startDateTime'], param['endDateTime'])
            elif 'startDate' in param:
                return timetable.read_schedule(r['uni_id'], param['startDate'], param['endDate'])
            else:
                return timetable.read_schedule(r['uni_id'], param[:10]+"T00:00:00+"+param[20:25])

    except Exception as e:
        log("Exception ({}) thrown: {}. {} sent '{}'.".format(type(e).__name__, e, r['_id'], data['queryResult']['queryText']))
        return "I'm sorry, something went wrong understanding that. :("


def parse_message(data, uid):

    r = collection.find_one({"_id": uid})
    
    if not timetable.check_loggedIn(r['uni_id']):
        log("{} logging in again.".format(uid))
        login_result = timetable.login(r['uni_id'], (f.decrypt(r['uni_pw'])).decode())
    
        if not login_result:
            log("{} failed to log in.".format(uid))
            collection.delete_one({"_id": uid})
            collection.insert_one({"_id": wait_id+uid})
            return ("Whoops! Something went wrong; maybe your login details changed?\n"
                    "Register here: {}/register?key={}").format(app_url, uid)
    
    return handle_intent(data, r)


def log(message):
    print(message)          # print() is not good practice. Will be replaced.


if __name__ == "__main__":
    app.run(debug = False, port = 80)
