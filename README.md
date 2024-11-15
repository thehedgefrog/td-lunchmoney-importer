# TD -> Lunch Money Importer

[![Build Status](https://github.com/thehedgefrog/td-lunchmoney-importer/actions/workflows/build.yml/badge.svg)](https://github.com/thehedgefrog/td-lunchmoney-importer/actions/workflows/build.yml)
[![Latest Release](https://img.shields.io/github/v/release/thehedgefrog/td-lunchmoney-importer)](https://github.com/thehedgefrog/td-lunchmoney-importer/releases/latest)

Import TD Canada Trust QFX files into [Lunch Money](https://lunchmoney.app).

## Features

- Import transactions from TD QFX files (including those with multiple accounts)
- Match TD accounts to Lunch Money accounts
- Filter transactions by date
- Update account balances
- Persistent configuration
- Duplicate detection

## Installation

### From Releases
Download the latest release for your platform:
- Windows (x64)
- macOS (ARM64)
- Linux (x64)

### From Source
```bash
git clone https://github.com/thehedgefrog/td-lunchmoney-importer.git
cd td-lunchmoney-importer
pip install -r requirements.txt
python importer.py
```

### Usage
1. Get your Lunch Money API key from [Developer Settings](https://my.lunchmoney.app/developers)
2. Run the importer:
```
td-lunchmoney-importer path/to/file.qfx
```

3. On first run:
   - Enter your API key
   - Match your TD accounts to Lunch Money accounts
4. For subsequent runs:
   - Choose date filter (optional)
   - Review transactions
   - Confirm import
   - Update balances if needed

### Configuration
Configuration is stored in `~/.lunchmoney/.lunchmoney_config.json` is a base64 encoded file containing:

- API key
- Account mappings

### Dependencies
- Python 3.9+
- ofxparse
- lunchable

### Contributing
1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### License
Distributed under the MIT License. See `LICENSE` for more information.