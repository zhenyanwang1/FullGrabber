import tornado.ioloop
import tornado.web
from pymongo import MongoClient, ASCENDING, DESCENDING
from bson import ObjectId


class MainHandler(tornado.web.RequestHandler):
    def get(self):
        client = MongoClient()
        db = client["zhihu"]
        data = db["questions"].find()
        self.render("main.html", questions=data)
        client.close()


class QuestionHandler(tornado.web.RequestHandler):
    def get(self, question):
        client = MongoClient()
        db = client["zhihu"]
        data = db["questions"].find_one({"QuestionID": int(question)})
        comments = db["comments"].find({"ParentType": 1, "ParentID": int(question)}).sort("Seq", ASCENDING)
        answers = db["answers"].find({"QuestionID": int(question)}).sort("Seq", ASCENDING)
        self.render("question.html", title=data["Title"], content=data["Content"], comments=comments, answers=answers)
        client.close()

class AnswerHandler(tornado.web.RequestHandler):
    def get(self, answer):
        client = MongoClient()
        db = client["zhihu"]
        data = db["answers"].find_one({"AnswerID": int(answer)})
        comments = db["comments"].find({"ParentType": 2, "ParentID": int(answer)}).sort("Seq", ASCENDING)
        self.render("answer.html", answer_id=data["AnswerID"], content=data["Content"], comments=comments)
        client.close()


class ImageHandler(tornado.web.RequestHandler):
    def get(self, image_id):
        client = MongoClient()
        db = client["zhihu"]
        data = db["images"].find_one({"_id": ObjectId(image_id)})
        self.write(data["Data"])
        client.close()


application = tornado.web.Application([
    (r"/", MainHandler),
    (r"/question/([0-9]+)", QuestionHandler),
    (r"/answer/([0-9]+)", AnswerHandler),
    (r"/image/(.+)", ImageHandler)
])

if __name__ == "__main__":
    application.listen(8888)
    tornado.ioloop.IOLoop.instance().start()