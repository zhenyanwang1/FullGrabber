from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from urllib.request import urlopen
import json
from urllib.parse import urlparse
from pymongo import MongoClient
from bson import Binary


def parse(url):
    o = urlparse(url)
    parts = o.path.split("/")
    parts = [part for part in parts if part != ""]
    if len(parts) != 2 and len(parts) != 4:
        raise Exception("Malformed URL.")
    if parts[0] == "question" and len(parts) == 2:
        return 1, parts[1]
    elif parts[0] == "collection" and len(parts) == 2:
        return 3, parts[1]
    elif parts[0] == "people" and len(parts) == 2:
        return 4, parts[1]
    elif parts[0] == "question" and parts[2] == "answer" and len(parts) == 4:
        return 2, parts[1], parts[3]
    else:
        raise Exception("Malformed URL.")


def make_url(question_id, answer_id=None):
    if answer_id is None:
        return "http://www.zhihu.com/question/{question_id}".format(question_id=question_id)
    else:
        return "http://www.zhihu.com/question/{question_id}/answer/{answer_id}".format(question_id=question_id,
                                                                                       answer_id=answer_id)


def save_to(obj, fn):
    f = open(fn, "w")
    json.dump(obj, f, indent=2, ensure_ascii=False)
    f.close()


class DBClient:
    def __init__(self):
        client = MongoClient()
        db = client["zhihu"]
        self.questions = db["questions"]
        self.answers = db["answers"]
        self.comments = db["comments"]
        self.collections = db["collections"]
        self.images = db["images"]
        self.client = client

    def cleanup_question(self, question_id):
        self.questions.remove({"QuestionID": question_id}, True)
        self.comments.remove({"ParentType": 1, "ParentID": question_id})
        self.images.remove({"ParentType": 1, "ParentID": question_id})
        answers = self.answers.find({"QuestionID": question_id})
        for answer in answers:
            self.cleanup_answer(answer["AnswerID"])

    def cleanup_answer(self, answer_id):
        self.answers.remove({"AnswerID": answer_id}, True)
        self.comments.remove({"ParentType": 2, "ParentID": answer_id})
        self.images.remove({"ParentType": 2, "ParentID": answer_id})

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        del exc_type, exc_val, exc_tb
        self.client.close()


class Grabber(DBClient):
    def __init__(self):
        DBClient.__init__(self)
        co = webdriver.ChromeOptions()
        co.add_argument("--user-data-dir=/home/zhenyan/selenium-chromium/data/")
        co.add_argument("--blacklist-accelerated-compositing")  # ATI card workaround
        browser = webdriver.Chrome("./chromedriver", chrome_options=co)
        self.browser = browser

    def wait_until(self, o):
        try:
            WebDriverWait(self.browser, 30).until(o)
        except:
            print("Wait Failed!")

    def move_to(self, obj):
        ac = webdriver.ActionChains(self.browser)
        ac.move_to_element(obj)
        ac.perform()

    def good_get(self, url):
        while True:
            self.browser.get(url)
            if self.browser.title != "知乎":
                break

    def get_inner_html(self, obj):
        return self.browser.execute_script("return arguments[0].innerHTML;", obj)

    def get_inner_text(self, obj):
        return self.browser.execute_script("return arguments[0].innerText;", obj)

    def process_question(self, url):
        question_id = int(parse(url)[1])
        self.good_get(url)
        title_element = self.browser.find_element_by_css_selector("h2.zm-item-title")
        title = self.get_inner_text(title_element)
        if title.endswith("修改"):
            title = title[:-2]
        expand = self.browser.find_elements_by_css_selector("a.toggle-expand")
        if len(expand) == 1:
            expand = expand[0]
            self.move_to(expand)
            expand.click()
            self.wait_until(EC.invisibility_of_element_located((By.CSS_SELECTOR, "a.toggle-expand")))
        content_element = self.browser.find_element_by_css_selector("div.zm-editable-content")
        content = self.process_html(self.get_inner_html(content_element), 1, question_id)
        addcomment = self.browser.find_element_by_css_selector("a.toggle-comment")
        if addcomment.text != "添加评论":
            self.move_to(addcomment)
            addcomment.click()
            self.wait_until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.zm-item-comment")))
            lm_elements = self.browser.find_elements_by_name("load-more")
            if len(lm_elements) != 0:
                load_more = lm_elements[0]
                self.move_to(load_more)
                load_more.click()
            node_removal = lambda s: len(self.browser.find_elements_by_css_selector("a.load-more")) == 0
            self.wait_until(node_removal)
            comment_elements = self.browser.find_elements_by_class_name("zm-item-comment")
            comment_seq = 1
            for comment_element in comment_elements:
                author = comment_element.find_element_by_class_name("zm-comment-hd").text
                comment_content_element = comment_element.find_element_by_class_name("zm-comment-content")
                comment_text = self.get_inner_html(comment_content_element)
                self.comments.insert(
                    {"ParentType": 1, "ParentID": question_id, "Seq": comment_seq, "Author": author,
                     "Content": comment_text})
                comment_seq += 1
        answer_urls = []
        for answer in self.browser.find_elements_by_class_name("zm-item-answer"):
            answer_id = answer.get_attribute("data-atoken")
            answer_url = make_url(question_id, answer_id)
            answer_urls.append(answer_url)
        self.questions.insert({"QuestionID": question_id, "Title": title, "Content": content})
        seq = 1
        for answer_url in answer_urls:
            self.process_answer(answer_url, seq)
            seq += 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        del exc_type, exc_val, exc_tb
        self.browser.close()

    def process_answer(self, url, seq):
        try:
            print("Fetching " + url)
            self.good_get(url)
            parts = parse(url)
            question_id = int(parts[1])
            answer_id = int(parts[2])
            content_element = self.browser.find_element_by_css_selector(
                'div[data-action="/answer/content"]').find_element_by_tag_name("div")
            answer_author = self.browser.find_element_by_css_selector("h3.zm-item-answer-author-wrap").text
            content = self.process_html(self.get_inner_html(content_element), 2, answer_id)
            addcomment = self.browser.find_elements_by_name("addcomment")[1]  # avoid comments under the question
            if addcomment.text == "添加评论":
                has_comments = False
            else:
                has_comments = True
            if has_comments:
                self.move_to(addcomment)
                addcomment.click()
                self.wait_until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.zm-item-comment")))
                comment_elements = self.browser.find_elements_by_class_name("zm-item-comment")
                comment_seq = 1
                for comment_element in comment_elements:
                    comment_author = comment_element.find_element_by_class_name("zm-comment-hd").text
                    comment_content_element = comment_element.find_element_by_class_name("zm-comment-content")
                    comment_text = self.get_inner_html(comment_content_element)
                    self.comments.insert(
                        {"ParentType": 2, "ParentID": answer_id, "Seq": comment_seq, "Author": comment_author,
                         "Content": comment_text})
                    comment_seq += 1
            print("Fetched " + url)
            self.answers.insert(
                {"QuestionID": question_id, "AnswerID": answer_id, "Seq": seq, "Author": answer_author,
                 "Content": content})
        except Exception as e:
            print("Failed! " + url)
            raise e  # for traceback

    @staticmethod
    def fetch_as_bytes(url):
        while True:
            try:
                return urlopen(url).read()
            except:
                pass

    def process_html(self, html, parent_type, parent_id):
        html = html.replace("<br>", "<br/>")  # no more "clever" tag closing
        soup = BeautifulSoup(html, "html.parser")
        for img in soup.find_all("img"):
            cls = img.get("class") or ""
            if "content_image" in cls and "lazy" in cls:
                image_url = img["data-actualsrc"]
            elif "origin_image" in cls:
                image_url = img["data-original"]
            elif "content_image" in cls and not "lazy" in cls:
                image_url = img["src"]
            else:
                image_url = img["src"]
            data = self.fetch_as_bytes(image_url)
            image_id = self.images.insert(
                {"ImageURL": image_url, "Data": Binary(data), "ParentType": parent_type, "ParentID": parent_id})
            img["src"] = "/image/{image_id}".format(image_id=image_id)
        edit_button = soup.find("a", class_="zu-edit-button")
        if edit_button:
            edit_button.extract()
        return str(soup)

    def process_people_page(self, url):
        #FIXME
        self.browser.get(url)
        answer_url_elements = self.browser.find_element_by_css_selector("a.question_link")
        urls = [answer_url_element.get_attribute("href") for answer_url_element in answer_url_elements]
        pagers = self.browser.find_elements_by_class_name("border-pager")
        if len(pagers) != 0:
            pager = pagers[0]
            if pager.find_elements_by_tag_name("span")[-1].get_attribute("class") != "":
                return urls, False
            else:
                return urls, True
        else:
            return urls, False

    def process_collection_page(self, url):
        #FIXME
        self.browser.get(url)
        answers = self.browser.find_elements(By.CLASS_NAME, "zm-item")
        question_ids = [] # For multiple answers under the same question
        urls = []
        for answer in answers:
            titles = answer.find_elements_by_class_name("zm-item-title")
            if len(titles) != 0:
                question_id = titles[0].find_element_by_tag_name("a").get_attribute("href").split("/")[-1]
                question_ids.append(question_id)
            else:
                question_id = question_ids[-1]
            answer_id = answer.find_element_by_class_name("zm-item-answer").get_attribute("data-atoken")
            urls.append(make_url(question_id, answer_id))
        pagers = self.browser.find_elements_by_class_name("border-pager")
        if len(pagers) != 0:
            pager = pagers[0]
            if pager.find_elements_by_tag_name("span")[-1].get_attribute("class") != "":
                return urls, False
            else:
                return urls, True
        else:
            return urls, False

    def process_collection(self, url):
        #FIXME
        page1 = self.process_collection_page(url + "?page=1")
        pages = []
        pages.append(page1)
        if page1[1]:
            pos = 2
            while True:
                page = self.process_collection_page(url + "?page={0}".format(pos))
                pages.append(page)
                if not page[1]:
                    break
                pos += 1
        return sum([page[0] for page in pages], [])

    def process_people(self, url):
        #FIXME
        first_page = self.process_people_page(url + "?page=1")
        pages = []
        pages.append(first_page)
        if first_page[1]:
            pos = 2
            while True:
                page = self.process_people_page(url + "?page={0}".format(pos))
                pages.append(page)
                if not page[1]:
                    break
                pos += 1
        return sum([page[0] for page in pages], [])