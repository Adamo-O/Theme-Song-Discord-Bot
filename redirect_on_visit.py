from pydoc import render_doc
from flask import Flask, redirect, render_template

app = Flask(__name__)

@app.route('/')
def home():
  return redirect('https://github.com/Adamo-O/Theme-Song-Discord-Bot#readme')