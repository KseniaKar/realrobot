# Realrobot — инструкции для агентов

## Python на этой машине

На этой машине Python **не в PATH** в Git Bash. Используй полный путь:

| Версия | Путь | Когда использовать |
|--------|------|--------------------|
| Python 3.9.6 | `C:\Program Files\Python39\python.exe` | Основной для проекта (здесь установлены streamlit, pandas, folium) |
| Python 3.12.7 | `C:\anaconda\python.exe` | Anaconda-окружение |

**В PowerShell:**
```powershell
& "C:\Program Files\Python39\python.exe" script.py
```

**В Bash (Git Bash / MINGW64):**
```bash
"/c/Program Files/Python39/python.exe" script.py
```

Для запуска Streamlit-приложения:
```bash
"/c/Users/Ксения/AppData/Roaming/Python/Python39/Scripts/streamlit.exe" run property_goals/app.py
```

> Shell — MINGW64 (Git Bash). `python`, `python3`, `py` в PATH не работают.
