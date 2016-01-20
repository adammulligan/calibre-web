#!/usr/bin/env python
# -*- coding: utf-8 -*-

import mimetypes
mimetypes.add_type('application/xhtml+xml','.xhtml')
from flask import Flask, render_template, session, request, Response, redirect, url_for, send_from_directory, make_response, g, flash, abort
from cps import db, config, ub, helper
import os
from sqlalchemy.sql.expression import func
from sqlalchemy.exc import IntegrityError
from math import ceil
from flask.ext.login import LoginManager, login_user, logout_user, login_required, current_user
from flask.ext.principal import Principal, Identity, AnonymousIdentity, identity_changed
import requests, zipfile
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import base64

app = (Flask(__name__))

Principal(app)

lm = LoginManager(app)
lm.init_app(app)
lm.login_view = 'login'

app.secret_key = 'A0Zr98j/3yX R~XHH!jmN]LWX/,?RT'

@lm.user_loader
def load_user(id):
    return ub.session.query(ub.User).filter(ub.User.id == int(id)).first()


@lm.header_loader
def load_user_from_header(header_val):
    if header_val.startswith('Basic '):
        header_val = header_val.replace('Basic ', '', 1)
    try:
        header_val = base64.b64decode(header_val)
        basic_username = header_val.split(':')[0]
        basic_password = header_val.split(':')[1]
        #print basic_username
        #print basic_password
    except TypeError:
        pass
    user = ub.session.query(ub.User).filter(ub.User.nickname == basic_username).first()
    if user and check_password_hash(user.password, basic_password):
        return user
    return

def check_auth(username, password):
    user = ub.session.query(ub.User).filter(ub.User.nickname == username).first()
    if user and check_password_hash(user.password, password):
        return True
    else:
        return False

def authenticate():
    return Response(
    'Could not verify your access level for that URL.\n'
    'You have to login with proper credentials', 401,
    {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_basic_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

#simple pagination for the feed
class Pagination(object):

    def __init__(self, page, per_page, total_count):
        self.page = page
        self.per_page = per_page
        self.total_count = total_count

    @property
    def pages(self):
        return int(ceil(self.total_count / float(self.per_page)))

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def has_next(self):
        return self.page < self.pages

    def iter_pages(self, left_edge=2, left_current=2,
                   right_current=5, right_edge=2):
        last = 0
        for num in xrange(1, self.pages + 1):
            if num <= left_edge or \
               (num > self.page - left_current - 1 and \
                num < self.page + right_current) or \
               num > self.pages - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num

##pagination links in jinja
def url_for_other_page(page):
    args = request.view_args.copy()
    args['page'] = page
    return url_for(request.endpoint, **args)

app.jinja_env.globals['url_for_other_page'] = url_for_other_page


def admin_required(f):
    """
    Checks if current_user.role == 1
    """
    @wraps(f)
    def inner(*args, **kwargs):
        if int(current_user.role) == 1:
            return f(*args, **kwargs)
        abort(403)
    return inner

@app.before_request
def before_request():
    g.user = current_user
    g.public_shelfes = ub.session.query(ub.Shelf).filter(ub.Shelf.is_public == 1).all()
    g.allow_registration = config.PUBLIC_REG

@app.route("/feed")
def feed_index():
    xml = render_template('index.xml')
    response= make_response(xml)
    response.headers["Content-Type"] = "application/xml"
    return response

@app.route("/feed/osd")
def feed_osd():
    xml = render_template('osd.xml')
    response= make_response(xml)
    response.headers["Content-Type"] = "application/xml"
    return response

@app.route("/feed/search", methods=["GET"])
def feed_search():
    term = request.args.get("query")
    if term:
        entries = db.session.query(db.Books).filter(db.or_(db.Books.tags.any(db.Tags.name.like("%"+term+"%")),db.Books.authors.any(db.Authors.name.like("%"+term+"%")),db.Books.title.like("%"+term+"%"))).all()
        xml = render_template('feed.xml', searchterm=term, entries=entries)
    else:
        xml = render_template('feed.xml', searchterm="")
    response= make_response(xml)
    response.headers["Content-Type"] = "application/xml"
    return response

@app.route("/feed/new")
def feed_new():
    off = request.args.get("start_index")
    if off:
        entries = db.session.query(db.Books).order_by(db.Books.last_modified.desc()).offset(off).limit(config.NEWEST_BOOKS)
    else:
        entries = db.session.query(db.Books).order_by(db.Books.last_modified.desc()).limit(config.NEWEST_BOOKS)
        off = 0
    xml = render_template('feed.xml', entries=entries, next_url="/feed/new?start_index=%d" % (int(config.NEWEST_BOOKS) + int(off)))
    response= make_response(xml)
    response.headers["Content-Type"] = "application/xml"
    return response


@app.route("/feed/discover")
def feed_discover():
    off = request.args.get("start_index")
    if off:
        entries = db.session.query(db.Books).order_by(func.random()).offset(off).limit(config.NEWEST_BOOKS)
    else:
        entries = db.session.query(db.Books).order_by(func.random()).limit(config.NEWEST_BOOKS)
        off = 0
    xml = render_template('feed.xml', entries=entries, next_url="/feed/discover?start_index=%d" % (int(config.NEWEST_BOOKS) + int(off)))
    response= make_response(xml)
    response.headers["Content-Type"] = "application/xml"
    return response

@app.route("/feed/hot")
def feed_hot():
    off = request.args.get("start_index")
    if off:
        entries = db.session.query(db.Books).filter(db.Books.ratings.any(db.Ratings.rating > 9)).offset(off).limit(config.NEWEST_BOOKS)
    else:
        entries = db.session.query(db.Books).filter(db.Books.ratings.any(db.Ratings.rating > 9)).limit(config.NEWEST_BOOKS)
        off = 0

    xml = render_template('feed.xml', entries=entries, next_url="/feed/hot?start_index=%d" % (int(config.NEWEST_BOOKS) + int(off)))
    response= make_response(xml)
    response.headers["Content-Type"] = "application/xml"
    return response

@app.route("/feed/download/<int:book_id>/<format>")
@requires_basic_auth
def get_opds_download_link(book_id, format):
    format = format.split(".")[0]
    book = db.session.query(db.Books).filter(db.Books.id == book_id).first()
    data = db.session.query(db.Data).filter(db.Data.book == book.id).filter(db.Data.format == format.upper()).first()
    helper.update_download(book_id, int(current_user.id))
    response = make_response(send_from_directory(os.path.join(config.DB_ROOT, book.path), data.name + "." +format))
    response.headers["Content-Disposition"] = "attachment; filename=%s.%s" % (data.name, format)
    return response

@app.route("/", defaults={'page': 1})
@app.route('/page/<int:page>')
def index(page):
    random = db.session.query(db.Books).order_by(func.random()).limit(config.RANDOM_BOOKS)
    if page == 1:
        entries = db.session.query(db.Books).order_by(db.Books.last_modified.desc()).limit(config.NEWEST_BOOKS)
    else:
        off = int(int(config.NEWEST_BOOKS) * (page - 1))
        entries = db.session.query(db.Books).order_by(db.Books.last_modified.desc()).offset(off).limit(config.NEWEST_BOOKS)
    pagination = Pagination(page, config.NEWEST_BOOKS, len(db.session.query(db.Books).all()))
    return render_template('index.html', random=random, entries=entries, pagination=pagination, title="Latest Books")

@app.route("/hot", defaults={'page': 1})
@app.route('/hot/page/<int:page>')
def hot_books(page):
    # if page == 1:
    #     entries = db.session.query(db.Books).filter(db.Books.ratings.any(db.Ratings.rating > 9)).order_by(db.Books.last_modified.desc()).limit(config.NEWEST_BOOKS)
    # else:
    #     off = int(int(config.NEWEST_BOOKS) * (page - 1))
    #     entries = db.session.query(db.Books).filter(db.Books.ratings.any(db.Ratings.rating > 9)).order_by(db.Books.last_modified.desc()).offset(60).limit(config.NEWEST_BOOKS)

    off = int(int(6) * (page - 1))
    all_books = ub.session.query(ub.Downloads, ub.func.count(ub.Downloads.book_id)).order_by(ub.func.count(ub.Downloads.book_id).desc()).group_by(ub.Downloads.book_id)
    hot_books = all_books.offset(off).limit(config.NEWEST_BOOKS)
    entries = list()
    for book in hot_books:
        entries.append(db.session.query(db.Books).filter(db.Books.id == book.Downloads.book_id).first())

    pagination = Pagination(page, config.NEWEST_BOOKS, len(all_books.all()))
    return render_template('index.html', entries=entries, pagination=pagination, title="Hot Books (most downloaded)")

@app.route("/stats")
def stats():
    counter = len(db.session.query(db.Books).all())
    return render_template('stats.html', counter=counter, title="Statistics")

@app.route("/discover", defaults={'page': 1})
@app.route('/discover/page/<int:page>')
def discover(page):
    if page == 1:
        entries = db.session.query(db.Books).order_by(func.randomblob(2)).limit(config.NEWEST_BOOKS)
    else:
        off = int(int(config.NEWEST_BOOKS) * (page - 1))
        entries = db.session.query(db.Books).order_by(func.randomblob(2)).offset(off).limit(config.NEWEST_BOOKS)
    pagination = Pagination(page, config.NEWEST_BOOKS, len(db.session.query(db.Books).all()))
    return render_template('discover.html', entries=entries, pagination=pagination, title="Random Books")

@app.route("/book/<int:id>")
def show_book(id):
    entries = db.session.query(db.Books).filter(db.Books.id == id).first()
    book_in_shelfs = []
    shelfs = ub.session.query(ub.BookShelf).filter(ub.BookShelf.book_id == id).all()
    for entry in shelfs:
        book_in_shelfs.append(entry.shelf)
    return render_template('detail.html', entry=entries,  title=entries.title, books_shelfs=book_in_shelfs)

@app.route("/category")
def category_list():
    entries = db.session.query(db.Tags).order_by(db.Tags.name).all()
    return render_template('categories.html', entries=entries, title="Category list")

@app.route("/category/<name>")
def category(name):
    if name != "all":
        entries = db.session.query(db.Books).filter(db.Books.tags.any(db.Tags.name.like("%" +name + "%" ))).order_by(db.Books.last_modified.desc()).all()
    else:
        entries = db.session.query(db.Books).all()
    return render_template('index.html', entries=entries, title="Category: %s" % name)

@app.route("/series/<name>")
def series(name):
    entries = db.session.query(db.Books).filter(db.Books.series.any(db.Series.name.like("%" +name + "%" ))).order_by(db.Books.series_index).all()
    return render_template('index.html', entries=entries, title="Series: %s" % name)


@app.route("/admin/")
def admin():
    #return "Admin ONLY!"
    abort(403)


@app.route("/search", methods=["GET"])
def search():
    term = request.args.get("query")
    if term:
        entries = db.session.query(db.Books).filter(db.or_(db.Books.tags.any(db.Tags.name.like("%"+term+"%")),db.Books.series.any(db.Series.name.like("%"+term+"%")),db.Books.authors.any(db.Authors.name.like("%"+term+"%")),db.Books.title.like("%"+term+"%"))).all()
        return render_template('search.html', searchterm=term, entries=entries)
    else:
        return render_template('search.html', searchterm="")

@app.route("/author")
def author_list():
    entries = db.session.query(db.Authors).order_by(db.Authors.sort).all()
    return render_template('authors.html', entries=entries, title="Author list")

@app.route("/author/<name>")
def author(name):
    entries = db.session.query(db.Books).filter(db.Books.authors.any(db.Authors.name.like("%" +  name + "%"))).all()
    return render_template('index.html', entries=entries, title="Author: %s" % name)

@app.route("/cover/<path:cover_path>")
def get_cover(cover_path):
    return send_from_directory(os.path.join(config.DB_ROOT, cover_path), "cover.jpg")

@app.route("/read/<int:book_id>")
@login_required
def read_book(book_id):
    book = db.session.query(db.Books).filter(db.Books.id == book_id).first()
    book_dir = os.path.join(config.MAIN_DIR, "cps","static", str(book_id))
    if not os.path.exists(book_dir):
        os.mkdir(book_dir)
        for data in book.data:
            if data.format.lower() == "epub":
                zfile = zipfile.ZipFile(os.path.join(config.DB_ROOT, book.path, data.name) + ".epub")
                for name in zfile.namelist():
                    (dirName, fileName) = os.path.split(name)
                    newDir = os.path.join(book_dir, dirName)
                    if not os.path.exists(newDir):
                        os.mkdir(newDir)
                    if fileName:
                        fd = open(os.path.join(newDir, fileName), "wb")
                        fd.write(zfile.read(name))
                        fd.close()
                zfile.close()
    return render_template('read.html', bookid=book_id, title="Read a Book")

@app.route("/download/<int:book_id>/<format>")
@login_required
def get_download_link(book_id, format):
    format = format.split(".")[0]
    book = db.session.query(db.Books).filter(db.Books.id == book_id).first()
    data = db.session.query(db.Data).filter(db.Data.book == book.id).filter(db.Data.format == format.upper()).first()
    helper.update_download(book_id, int(current_user.id))
    response = make_response(send_from_directory(os.path.join(config.DB_ROOT, book.path), data.name + "." +format))
    response.headers["Content-Disposition"] = "attachment; filename=%s.%s" % (data.name, format)
    return response

@app.route('/register', methods = ['GET', 'POST'])
def register():
    error = None
    if not config.PUBLIC_REG:
        abort(404)
    if current_user is not None and current_user.is_authenticated():
        return redirect(url_for('index'))

    if request.method == "POST":
        to_save = request.form.to_dict()
        if not to_save["nickname"] or not to_save["email"] or not to_save["password"]:
            flash("Please fill out all fields!", category="error")
            return render_template('register.html', title="register")

        existing_user = ub.session.query(ub.User).filter(ub.User.nickname == to_save["nickname"]).first()
        existing_email = ub.session.query(ub.User).filter(ub.User.email == to_save["email"]).first()
        if not existing_user and not existing_email:
            content = ub.User()
            content.password = generate_password_hash(to_save["password"])
            content.nickname = to_save["nickname"]
            content.email = to_save["email"]
            content.role = 0
            try:
                ub.session.add(content)
                ub.session.commit()
            except:
                ub.session.rollback()
                flash("An unknown error occured. Please try again later.", category="error")
                return render_template('register.html', title="register")
            flash("Your account has been created. Please login.", category="success")
            return redirect(url_for('login'))
        else:
            flash("This username or email address is already in use.", category="error")
            return render_template('register.html', title="register")

    return render_template('register.html', title="register")

@app.route('/login', methods = ['GET', 'POST'])
def login():
    error = None

    if current_user is not None and current_user.is_authenticated():
        return redirect(url_for('index'))

    if request.method == "POST":
        form = request.form.to_dict()
        user = ub.session.query(ub.User).filter(ub.User.nickname == form['username']).first()

        if user and check_password_hash(user.password, form['password']):
            login_user(user, remember = True)
            flash("you are now logged in as: '%s'" % user.nickname, category="success")
            return redirect(request.args.get("next") or url_for("index"))
        else:
            flash("Wrong Username or Password", category="error")

    return render_template('login.html', title="login")

@app.route('/logout')
@login_required
def logout():
    if current_user is not None and current_user.is_authenticated():
        logout_user()
    return redirect(request.args.get("next") or url_for("index"))


@app.route('/send/<int:book_id>')
@login_required
def send_to_kindle(book_id):
    settings = ub.get_mail_settings()
    if settings.get("mail_server", "mail.example.com") == "mail.example.com":
        flash("Please configure the SMTP email account first...", category="error")
    elif current_user.kindle_mail:
        x = helper.send_mail(book_id, current_user.kindle_mail)
        if x:
            flash("Mail successfully send to %s" % current_user.kindle_mail, category="success")
            helper.update_download(book_id, int(current_user.id))
        else:
            flash("There was an error sending this book", category="error")
    else:
        flash("Please set a kindle mail first...", category="error")
    return redirect(request.environ["HTTP_REFERER"])

@app.route("/shelf/add/<int:shelf_id>/<int:book_id>")
@login_required
def add_to_shelf(shelf_id, book_id):
    shelf = ub.session.query(ub.Shelf).filter(ub.Shelf.id == shelf_id).first()
    if not shelf.is_public and not shelf.user_id == int(current_user.id):
        flash("Sorry you are not allowed to add a book to the the shelf: %s" % shelf.name)
        return redirect(url_for('index'))

    ins = ub.BookShelf(shelf=shelf.id, book_id=book_id)
    ub.session.add(ins)
    ub.session.commit()

    flash("Book has been added to shelf: %s" % shelf.name, category="success")

    #return redirect(url_for('show_book', id=book_id))
    return redirect(request.environ["HTTP_REFERER"])

@app.route("/shelf/remove/<int:shelf_id>/<int:book_id>")
@login_required
def remove_from_shelf(shelf_id, book_id):
    shelf = ub.session.query(ub.Shelf).filter(ub.Shelf.id == shelf_id).first()
    if not shelf.is_public and not shelf.user_id == int(current_user.id):
        flash("Sorry you are not allowed to remove a book from this shelf: %s" % shelf.name)
        return redirect(url_for('index'))

    book_shelf = ub.session.query(ub.BookShelf).filter(ub.BookShelf.shelf == shelf_id, ub.BookShelf.book_id == book_id).first()

    #rem = ub.BookShelf(shelf=shelf.id, book_id=book_id)
    ub.session.delete(book_shelf)
    ub.session.commit()

    flash("Book has been removed from shelf: %s" % shelf.name, category="success")

    return redirect(request.environ["HTTP_REFERER"])

@app.route("/shelf/create", methods=["GET", "POST"])
@login_required
def create_shelf():
    shelf = ub.Shelf()
    if request.method == "POST":
        to_save = request.form.to_dict()
        if "is_public" in to_save:
            shelf.is_public = 1
        shelf.name = to_save["title"]
        shelf.user_id = int(current_user.id)
        existing_shelf = ub.session.query(ub.Shelf).filter(ub.Shelf.name == shelf.name).first()
        if existing_shelf:
            flash("A shelf with the name '%s' already exists." % to_save["title"], category="error")
        else:
            try:
                ub.session.add(shelf)
                ub.session.commit()
                flash("Shelf %s created" % to_save["title"], category="success")
            except:
                flash("There was an error", category="error")
        return render_template('shelf_edit.html', title="create a shelf")
    else:
        return render_template('shelf_edit.html', title="create a shelf")


@app.route("/shelf/<int:shelf_id>")
@login_required
def show_shelf(shelf_id):
    shelf = ub.session.query(ub.Shelf).filter(ub.or_(ub.and_(ub.Shelf.user_id == int(current_user.id), ub.Shelf.id == shelf_id), ub.and_(ub.Shelf.is_public == 1, ub.Shelf.id == shelf_id))).first()
    result = list()
    if shelf:
        books_in_shelf = ub.session.query(ub.BookShelf).filter(ub.BookShelf.shelf == shelf_id).all()
        for book in books_in_shelf:
            cur_book = db.session.query(db.Books).filter(db.Books.id == book.book_id).first()
            result.append(cur_book)

    return render_template('shelf.html', entries=result, title="Shelf: '%s'" % shelf.name)

@app.route("/me", methods = ["GET", "POST"])
@login_required
def profile():
    content = ub.session.query(ub.User).filter(ub.User.id == int(current_user.id)).first()
    downloads = list()
    for book in content.downloads:
        downloads.append(db.session.query(db.Books).filter(db.Books.id == book.book_id).first())
    if request.method == "POST":
        to_save = request.form.to_dict()
        #print to_save
        if to_save["password"]:
            content.password = generate_password_hash(to_save["password"])
        if to_save["kindle_mail"] and to_save["kindle_mail"] != content.kindle_mail:
            content.kindle_mail = to_save["kindle_mail"]
        if to_save["email"] and to_save["email"] != content.email:
            content.email = to_save["email"]
        try:
            ub.session.commit()
        except IntegrityError:
            ub.session.rollback()
            flash("Found an existing account for this email address.", category="error")
            return render_template("user_edit.html", content=content, downloads=downloads, title="%s's profile" % current_user.nickname)
        flash("Profile updated", category="success")
    return render_template("user_edit.html", profile=1, content=content, downloads=downloads, title="%s's profile" % current_user.nickname)

@app.route("/admin/user")
@login_required
@admin_required
def user_list():
    content = ub.session.query(ub.User).all()
    settings = ub.session.query(ub.Settings).first()
    return render_template("user_list.html", content=content, email=settings, title="User list")

@app.route("/admin/user/new", methods = ["GET", "POST"])
@login_required
@admin_required
def new_user():
    content = ub.User()
    if request.method == "POST":
        to_save = request.form.to_dict()
        if not to_save["nickname"] or not to_save["email"] or not to_save["password"]:
            flash("Please fill out all fields!", category="error")
            return render_template("user_edit.html", new_user=1, content=content, title="Add new user")
        content.password = generate_password_hash(to_save["password"])
        content.nickname = to_save["nickname"]
        content.email = to_save["email"]
        if "admin_user" in to_save:
            content.role = 1
        else:
            content.role = 0
        try:
            ub.session.add(content)
            ub.session.commit()
            flash("User '%s' created" % content.nickname, category="success")
            return redirect(url_for('user_list'))
        except IntegrityError:
            ub.session.rollback()
            flash("Found an existing account for this email address or nickname.", category="error")
    return render_template("user_edit.html", new_user=1, content=content, title="Add new user")

@app.route("/admin/user/mailsettings", methods = ["GET", "POST"])
@login_required
@admin_required
def edit_mailsettings():
    content = ub.session.query(ub.Settings).first()
    if request.method == "POST":
        to_save = request.form.to_dict()
        content.mail_server = to_save["mail_server"]
        content.mail_port = int(to_save["mail_port"])
        content.mail_login = to_save["mail_login"]
        content.mail_password = to_save["mail_password"]
        content.mail_from = to_save["mail_from"]
        try:
            ub.session.commit()
            flash("Mail settings updated", category="success")
        except (e):
            flash(e, category="error")
    return render_template("email_edit.html", content=content, title="Edit mail settings")

@app.route("/admin/user/<int:user_id>", methods = ["GET", "POST"])
@login_required
@admin_required
def edit_user(user_id):
    content = ub.session.query(ub.User).filter(ub.User.id == int(user_id)).first()
    downloads = list()
    for book in content.downloads:
        downloads.append(db.session.query(db.Books).filter(db.Books.id == book.book_id).first())
    if request.method == "POST":
        to_save = request.form.to_dict()
        if "delete" in to_save:
            ub.session.delete(content)
            flash("User '%s' deleted" % content.nickname, category="success")
            return redirect(url_for('user_list'))
        else:
            if to_save["password"]:
                content.password == generate_password_hash(to_save["password"])
            if "admin_user" in to_save and content.role != 1:
                content.role = 1
            elif not "admin_user" in to_save and content.role == 1:
                content.role = 0
            if to_save["email"] and to_save["email"] != content.email:
                content.email = to_save["email"]
            if to_save["kindle_mail"] and to_save["kindle_mail"] != content.kindle_mail:
                content.kindle_mail = to_save["kindle_mail"]
        try:
            ub.session.commit()
            flash("User '%s' updated" % content.nickname, category="success")
        except IntegrityError:
            ub.session.rollback()
            flash("An unknown error occured.", category="error")
    return render_template("user_edit.html", new_user=0, content=content, downloads=downloads, title="Edit User %s" % content.nickname)

@app.route("/admin/book/<int:book_id>", methods=['GET', 'POST'])
@login_required
@admin_required
def edit_book(book_id):
    ## create the function for sorting...
    db.session.connection().connection.connection.create_function("title_sort",1,db.title_sort)
    book = db.session.query(db.Books).filter(db.Books.id == book_id).first()
    if request.method == 'POST':
        to_save = request.form.to_dict()
        #print to_save
        book.title = to_save["book_title"]
        book.authors[0].name = to_save["author_name"]

        if to_save["cover_url"] and os.path.splitext(to_save["cover_url"])[1].lower() == ".jpg":
            img = requests.get(to_save["cover_url"])
            f = open(os.path.join(config.DB_ROOT, book.path, "cover.jpg"), "wb")
            f.write(img.content)
            f.close()

        if book.series_index != to_save["series_index"]:
            book.series_index = to_save["series_index"]
        if len(book.comments):
            book.comments[0].text = to_save["description"]
        else:
            book.comments.append(db.Comments(text=to_save["description"], book=book.id))

        for tag in to_save["tags"].split(","):
            if tag.strip():
                #print tag
                is_tag = db.session.query(db.Tags).filter(db.Tags.name.like('%' + tag.strip() + '%')).first()
                if is_tag:
                    book.tags.append(is_tag)
                else:
                    new_tag = db.Tags(name=tag.strip())
                    book.tags.append(new_tag)
        if to_save["series"].strip():
            is_series = db.session.query(db.Series).filter(db.Series.name.like('%' + to_save["series"].strip() + '%')).first()
            if is_series:
                book.series.append(is_series)
            else:
                new_series = db.Series(name=to_save["series"].strip(), sort=to_save["series"].strip())
                book.series.append(new_series)
        if to_save["rating"].strip():
            is_rating = db.session.query(db.Ratings).filter(db.Ratings.rating == int(to_save["rating"].strip())).first()
            if is_rating:
                book.ratings[0] = is_rating
            else:
                new_rating = db.Ratings(rating=int(to_save["rating"].strip()))
                book.ratings[0] = new_rating
        db.session.commit()
        if to_save["detail_view"]:
            return redirect(url_for('show_book', id=book.id))
        else:
            return render_template('edit_book.html', book=book)
    else:
        return render_template('edit_book.html', book=book)

# @app.route('/admin/delete/<int:book_id>')
# def delete_book(book_id):
#     to_delete = db.session.query(db.Books).filter(db.Books.id == book_id).first()
#     print to_delete
#     db.session.delete(to_delete)
#     db.session.commit()
#     return redirect(url_for('index'))
