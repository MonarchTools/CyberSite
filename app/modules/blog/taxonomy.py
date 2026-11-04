"""دسته‌بندی و برچسب پست‌های وبلاگ."""

import re

from sqlalchemy import func

from app.extensions import db
from app.modules.blog.models import BlogCategory, BlogTag, Post, post_tags
from app.modules.blog.slugs import slugify


MAX_TAGS = 8
TAG_MAX_LENGTH = 40

_TAG_SPLIT = re.compile(r"[,،;؛\n]+")


def parse_tags(text):
    """متن «a, b، c» → [(نام، slug)] بدون تکرار؛ حداکثر MAX_TAGS برچسب."""
    result, seen = [], set()

    for raw in _TAG_SPLIT.split(text or ""):
        name = " ".join(raw.split())[:TAG_MAX_LENGTH]
        slug = slugify(name)

        if not name or not slug or slug in seen:
            continue

        seen.add(slug)
        result.append((name, slug))

        if len(result) >= MAX_TAGS:
            break

    return result


def tags_from_text(text):
    """برچسب‌های موجود را برمی‌گرداند و تازه‌ها را می‌سازد (commit نمی‌کند)."""
    tags = []

    for name, slug in parse_tags(text):
        tag = BlogTag.query.filter_by(slug=slug).first()

        if tag is None:
            tag = BlogTag(name=name, slug=slug)
            db.session.add(tag)

        tags.append(tag)

    return tags


def tags_text(post):
    return "، ".join(tag.name for tag in post.tags)


def published_categories():
    """[(دسته، تعداد پست منتشرشده)] فقط دسته‌هایی که پست منتشرشده دارند."""
    return db.session.query(
        BlogCategory, func.count(Post.id)
    ).join(
        Post, Post.category_id == BlogCategory.id
    ).filter(
        Post.is_published.is_(True)
    ).group_by(BlogCategory.id).order_by(BlogCategory.name).all()


def published_tags(limit=30):
    return db.session.query(
        BlogTag, func.count(Post.id)
    ).join(
        post_tags, post_tags.c.tag_id == BlogTag.id
    ).join(
        Post, Post.id == post_tags.c.post_id
    ).filter(
        Post.is_published.is_(True)
    ).group_by(BlogTag.id).order_by(
        func.count(Post.id).desc(), BlogTag.name
    ).limit(limit).all()
