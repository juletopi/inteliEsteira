from flask import Blueprint, render_template


pages_bp = Blueprint("pages", __name__)


@pages_bp.get("/")
def dashboard():
    return render_template("dashboard.html")


@pages_bp.get("/linha-de-producao")
def production():
    return render_template("production.html")


@pages_bp.get("/conexao")
def connection():
    return render_template("connection.html")
