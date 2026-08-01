"""Public marketing site: home, features, pricing, performance, FAQ, docs,
changelog, contact, blog, status page, legal."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import optional_user
from app.models.billing import Plan, ReferralClick
from app.models.platform import Broker, CMSPost, ServerNode, Ticket, TicketMessage
from app.models.trading import Signal
from app.models.user import User
from app.templating import templates

router = APIRouter(tags=["public"])


def page(request: Request, name: str, user: User | None, **ctx):
    return templates.TemplateResponse(request, f"public/{name}.html", {"user": user, **ctx})


@router.get("/")
def home(request: Request, ref: str = "", db: Session = Depends(get_db), user=Depends(optional_user)):
    if ref:
        db.add(ReferralClick(referral_code=ref, ip=request.client.host if request.client else ""))
        db.commit()
    banners = db.query(CMSPost).filter_by(type="banner", published=True).all()
    announcements = db.query(CMSPost).filter_by(type="announcement", published=True).order_by(CMSPost.id.desc()).limit(3).all()
    return page(request, "home", user, banners=banners, announcements=announcements, ref=ref)


@router.get("/features")
def features(request: Request, user=Depends(optional_user)):
    return page(request, "features", user)


@router.get("/pricing")
def pricing(request: Request, db: Session = Depends(get_db), user=Depends(optional_user)):
    plans = db.query(Plan).filter_by(is_public=True).order_by(Plan.sort_order).all()
    return page(request, "pricing", user, plans=plans)


@router.get("/performance")
def performance(request: Request, db: Session = Depends(get_db), user=Depends(optional_user)):
    signals = db.query(Signal).order_by(Signal.created_at.desc()).limit(20).all()
    total = db.query(Signal).count()
    approved = db.query(Signal).filter(Signal.status.in_(["approved", "executed"])).count()
    return page(request, "performance", user, signals=signals, total=total, approved=approved)


@router.get("/faq")
def faq(request: Request, db: Session = Depends(get_db), user=Depends(optional_user)):
    items = db.query(CMSPost).filter_by(type="faq", published=True).all()
    return page(request, "faq", user, items=items)


@router.get("/docs-site")
def documentation(request: Request, db: Session = Depends(get_db), user=Depends(optional_user)):
    docs = db.query(CMSPost).filter(CMSPost.type.in_(["documentation", "tutorial"]), CMSPost.published).all()
    return page(request, "documentation", user, docs=docs)


@router.get("/changelog")
def changelog(request: Request, db: Session = Depends(get_db), user=Depends(optional_user)):
    notes = db.query(CMSPost).filter_by(type="changelog", published=True).order_by(CMSPost.id.desc()).all()
    return page(request, "changelog", user, notes=notes)


@router.get("/blog")
def blog(request: Request, db: Session = Depends(get_db), user=Depends(optional_user)):
    posts = (
        db.query(CMSPost)
        .filter(CMSPost.type.in_(["blog", "news"]), CMSPost.published)
        .order_by(CMSPost.id.desc())
        .all()
    )
    return page(request, "blog", user, posts=posts)


@router.get("/blog/{slug}")
def blog_post(slug: str, request: Request, db: Session = Depends(get_db), user=Depends(optional_user)):
    post = db.query(CMSPost).filter_by(slug=slug, published=True).first()
    return page(request, "blog_post", user, post=post)


@router.get("/status")
def status_page(request: Request, db: Session = Depends(get_db), user=Depends(optional_user)):
    nodes = db.query(ServerNode).order_by(ServerNode.role).all()
    brokers = db.query(Broker).filter_by(active=True).all()
    return page(request, "status", user, nodes=nodes, brokers=brokers)


@router.get("/contact")
def contact(request: Request, user=Depends(optional_user)):
    return page(request, "contact", user, sent=False)


@router.post("/contact")
def contact_post(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    message: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(optional_user),
):
    label = name or email or "anonymous"
    ticket = Ticket(user_id=user.id if user else None, subject=f"Contact form: {label}", category="support")
    db.add(ticket)
    db.flush()
    db.add(TicketMessage(ticket_id=ticket.id, author_id=user.id if user else None, body=message))
    db.commit()
    return page(request, "contact", user, sent=True)


LEGAL_PAGES = {
    "terms": "Terms of Service",
    "privacy": "Privacy Policy",
    "risk-disclaimer": "Risk Disclaimer",
    "cookies": "Cookie Policy",
    "gdpr": "GDPR",
}


@router.get("/legal/{doc}")
def legal(doc: str, request: Request, db: Session = Depends(get_db), user=Depends(optional_user)):
    title = LEGAL_PAGES.get(doc, "Legal")
    post = db.query(CMSPost).filter_by(slug=f"legal-{doc}", published=True).first()
    return page(request, "legal", user, title=title, post=post, doc=doc)


@router.get("/downloads")
def downloads_public(request: Request, user=Depends(optional_user)):
    return page(request, "downloads", user)
