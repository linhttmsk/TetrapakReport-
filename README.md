# Tetrapak Tool

Streamlit-based logistics tool for Tetra Pak shipment management.

## Project Structure
```
tetrapak_tool/
├── .github/
│   └── workflows/
│       └── build.yml          ← GitHub Actions: build Windows + Mac
├── app/
│   ├── .streamlit/
│   │   ├── config.ini         ← SQL + app config
│   │   └── config.toml        ← Streamlit theme
│   ├── pages/
│   │   ├── 1_Daily_Shipment.py
│   │   ├── 2_OPS_Loading.py
│   │   ├── 3_Loading_Performance.py
│   │   ├── 4_Container_Inventory.py
│   │   ├── 5_Report.py
│   │   └── 6_Configuration.py
│   └── Home.py
├── scripts/
│   └── setup.iss              ← Inno Setup script (Windows installer)
├── IMA.py                     ← Entry point (launch Streamlit)
├── requirements.txt
└── README.md
```

## Development
```bash
pip install -r requirements.txt
streamlit run app/Home.py
```

## Release Process
```
1. Finish code changes
2. git tag v1.0.1
3. git push origin v1.0.1
4. GitHub Actions auto:
   - Build Windows .exe → Inno Setup installer
   - Build Mac .app → zip
   - Create GitHub Release with both files
5. VBA in Excel checks GitHub API → downloads installer → runs silently
```

## VBA Version Check (GitHub Releases API)
```vb
' Check latest version
https://api.github.com/repos/YOUR_USERNAME/tetrapak_tool/releases/latest

' Response: {"tag_name":"v1.0.1","assets":[{"browser_download_url":"..."}]}
```

## Config
Edit `app/.streamlit/config.ini`:
- `[APP]` section: app name, version
- `[SQL]` section: SQL Server connection details
