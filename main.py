"""
HADES V103 - Autonomous Self-Evolving AI Prediction System
نظام تنبؤ هجين: معادلة رياضية + تحليل بايزي + NVIDIA AI + قوانين ذكية
يعمل على Railway مع PostgreSQL - واجهة أزرار تفاعلية كاملة
"""

import os, sys, datetime, psycopg2, pandas as pd, numpy as np
import json, re, logging, random, secrets
from typing import Dict, List, Tuple, Optional, Any
from pathlib import Path
from collections import Counter

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler,
    CommandHandler, ContextTypes, JobQueue
)
from openai import OpenAI

# ==================== 🛡️ الإعدادات الأساسية ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ✅ المفاتيح - كما طلبت تبقى كما هي
TOKEN = "8706937528:AAHVug63kujbf2t2ntKiQzpa3IN6Wr5b16s"
DATABASE_URL = "postgresql://postgres:MvqqjPDwAqRkGGLVfBUedIbceHNkcIFx@maglev.proxy.rlwy.net:53865/railway"
ADMIN_ID = 6033203084

NVIDIA_API_KEY = "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"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "minimaxai/minimax-m2.5"

# ثوابت النظام
WARMUP_ROUNDS = 700
WINNER_MAP = {
    'الراعي 🔴': 0, 'راعي': 0, 'الثور 🔵': 1, 'ثور': 1,
    'تعادل ⚪': 2, 'تعادل': 2, '🔴': 0, '🔵': 1, '⚪': 2
}
WINNER_NAMES = {0: 'الراعي 🔴', 1: 'الث
