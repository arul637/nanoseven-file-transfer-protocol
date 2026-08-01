from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class Share(db.Model):
    __tablename__ = 'shares'

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.Integer, unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=True)
    salt = db.Column(db.String(64), nullable=True)
    download_limit = db.Column(db.Integer, nullable=True)
    downloads = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    expires_at = db.Column(db.DateTime, nullable=False)

    files = db.relationship('SharedFile', backref='share', lazy='dynamic',
                            cascade='all, delete-orphan')

    @property
    def token_str(self):
        return f'{self.token:06d}'

    @property
    def limit_label(self):
        return 'Unlimited' if self.download_limit is None else str(self.download_limit)

    @property
    def remaining(self):
        if self.download_limit is None:
            return None
        return max(0, self.download_limit - self.downloads)

    @property
    def expired(self):
        return datetime.now() > self.expires_at

    @property
    def limit_reached(self):
        return self.download_limit is not None and self.downloads >= self.download_limit

    @property
    def usable(self):
        return not self.expired and not self.limit_reached

    @property
    def protected(self):
        return self.password_hash is not None

    def set_password(self, password):
        if password:
            self.password_hash = generate_password_hash(password)
        else:
            self.password_hash = None

    def check_password(self, password):
        if self.password_hash is None:
            return True
        return check_password_hash(self.password_hash, password)


class SharedFile(db.Model):
    __tablename__ = 'shared_files'

    id = db.Column(db.Integer, primary_key=True)
    share_id = db.Column(db.Integer, db.ForeignKey('shares.id'), nullable=False)
    original_filename = db.Column(db.String(512), nullable=False)
    stored_filename = db.Column(db.String(256), nullable=False)
    size = db.Column(db.Integer, default=0)
    encrypted = db.Column(db.Boolean, default=False)

    @property
    def size_display(self):
        s = self.size
        if s < 1024:
            return f'{s} B'
        if s < 1024 * 1024:
            return f'{s / 1024:.1f} KB'
        if s < 1024 * 1024 * 1024:
            return f'{s / (1024 * 1024):.1f} MB'
        return f'{s / (1024 * 1024 * 1024):.2f} GB'
