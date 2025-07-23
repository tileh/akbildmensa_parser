# 🥗 OpenMensa Parser – Akademie der bildenden Künste Wien

This repository provides an **automated parser** for the daily menu of the [Akademie der bildenden Künste Wien (Akbild)](https://www.akbild.ac.at/).  
It scrapes the published menu from the Akbild website, converts it into the standardized [OpenMensa](https://openmensa.org/) feed format, and publishes it as an XML feed.

## What It Does

- Fetches the weekly menu from the Akbild [Mensa page](https://www.akbild.ac.at/de/universitaet/services/menueplan)
- Parses meals by weekday and identifies their category:
  - 🥩 Non-vegetarian (`nicht vegetarisch`)
  - 🥬 Vegetarian (`vegetarisch`)
  - 🌱 Vegan (`vegan`)
- Assigns basic pricing based on the meal type
- Outputs structured XML in [OpenMensa feed format](https://github.com/opendatajson/food#openmensa-feed-v2)
- Automatically publishes the feed via GitHub Pages

## How to Run the Parser Locally

Make sure you have Python 3.8+ installed. Then:

```bash
pip install -r requirements.txt
python main.py
```

The generated OpenMensa feed will be saved in:

```
feed/akbild.xml
```

You can then preview it or serve it locally.

## GitHub Actions Automation

This repository uses **GitHub Actions** to automatically run the parser and publish the result.

## 📄 License

This project is licensed under the **MIT License**.  
See the [LICENSE](LICENSE) file for more information.

## 🤝 Contributing

Contributions are welcome! Feel free to:

- Open an issue for bugs or feature suggestions
- Submit a pull request
- Improve the parser logic or support additional formats (e.g., JSON or metadata)

---

Built with 🧡 for open data and hungry students.
