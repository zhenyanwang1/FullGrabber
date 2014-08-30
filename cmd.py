import argparse
import grab
import time
import subprocess
import socket

parser = argparse.ArgumentParser(description='FullGrabber Commmand-line Tool')
parser.add_argument("-c", "--clear", type=int, metavar="ID", dest="id",
                    help="Wipe all data with this question_id from the database.")
parser.add_argument("-u", "--url", type=str, metavar="URL", dest="url", help="Grab the url.")
parser.add_argument("-t", "--test", help="Test the configuration of the browser.", dest="test", action="store_true")
parser.add_argument("-w", "--web", help="Start the web frontend.", dest="web", action="store_true")
parser.add_argument("-to", "--timeout", type=int, help="Start the web frontend.", dest="timeout")
args = parser.parse_args()
if args.timeout:
    socket.setdefaulttimeout(args.timeout)  # For bad networks.
if args.id:
    with grab.DBClient() as dbc:
        dbc.cleanup_question(args.id)
elif args.test:
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Finished.")
elif args.web:
    subprocess.call("(python web.py &> /dev/null&)", shell=True)
elif args.url:
    with grab.Grabber() as grabber:
        grabber.process_question(args.url)
