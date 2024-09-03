# FastAPI Trading Application

This is a FastAPI application for managing trading operations in the Indian futures and options market. The application is deployed on Heroku.

## Features

- Modularized trading operations
- Improved logging and error handling
- Enhanced readability and maintainability
- Type hints for better code clarity
- Environment-specific configurations

## Directory Structure

fastapi-trading-app/
├── app/
│   ├── api/
│   │   ├── trade/
│   │   │   ├── binance/
│   │   │   │   └── __init__.py
│   │   │   ├── capital/
│   │   │   │   ├── __init__.py
│   │   │   │   └── tasks.py
│   │   │   ├── indian_fno/
│   │   │   │   ├── alice_blue/
│   │   │   │   │   └── utils.py
│   │   │   │   ├── angel_one/
│   │   │   │   │   ├── __init__.py
│   │   │   │   │   ├── broker_trading_operations.py
│   │   │   │   │   ├── db_operations.py
│   │   │   │   │   └── tasks.py
│   │   │   │   ├── zerodha/
│   │   │   │   │   ├── __init__.py
│   │   │   │   │   ├── broker_trading_operations.py
│   │   │   │   │   └── db_operations.py
│   │   │   ├── __init__.py
│   │   │   ├── healthcheck.py
│   │   │   ├── strategy.py
│   │   │   └── trade.py
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py
│   ├── create_app.py
│   ├── database/
│   │   ├── base.py
│   │   ├── queries.py
│   │   ├── schemas/
│   │   │   ├── daily_profit.py
│   │   │   └── __init__.py
│   │   └── session_manager/
│   │       ├── db_session.py
│   │       └── __init__.py
│   ├── extensions/
│   │   └── __init__.py
│   ├── main.py
│   ├── pydantic_models/
│   │   ├── strategy.py
│   │   └── __init__.py
│   ├── services/
│   │   └── __init__.py
│   ├── test/
│   │   ├── factory/
│   │   │   ├── base_factory.py
│   │   │   ├── create_async_session.py
│   │   │   ├── daily_profit.py
│   │   │   ├── strategy.py
│   │   │   ├── trade.py
│   │   │   ├── user.py
│   │   │   └── __init__.py
│   │   ├── unit_tests/
│   │   │   ├── test_apis/
│   │   │   │   ├── test_strategy.py
│   │   │   │   └── __init__.py
│   │   │   ├── test_cron/
│   │   │   │   └── __init__.py
│   │   │   ├── test_sql/
│   │   │   │   └── __init__.py
│   │   │   ├── test_utils/
│   │   │   │   ├── test_option_chain.py
│   │   │   │   └── __init__.py
│   │   │   └── __init__.py
│   │   ├── utils.py
│   │   └── __init__.py
│   ├── utils/
│   │   ├── constants.py
│   │   └── __init__.py
│   └── __init__.py
├── cron/
│   ├── scheduler.py
│   ├── clean_redis.py
│   ├── download_master_contracts.py
│   ├── __init__.py
├── alembic_migrations/
│   ├── versions/
│   │   ├── V1_first_migration.py
│   │   ├── V6_added_cfd_strategy_table.py
│   │   ├── V13_added_orders_table.py
│   │   └── __init__.py
│   ├── script.py.mako
│   └── __init__.py
├── .dockerignore
├── .gitignore
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── log.ini
├── newrelic.ini
├── Procfile
├── pyproject.toml
├── requirements.txt
├── runtime.txt
└── test_main.http


## Getting Started

### Prerequisites

- Python 3.8+
- FastAPI
- SQLAlchemy
- Heroku CLI (for deployment)

### Installation

1. **Clone the repository:**

    ```sh
    git clone https://github.com/MaheshKok/kkb_fastapi-copy.git
    cd your-repo
    ```

2. **Create a virtual environment:**

    ```sh
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3. **Install dependencies:**

    ```sh
    pip install -r requirements.txt
    ```

4. **Set up environment variables:**

    Create a `.env` file in the root directory and add your environment variables:

    ```env
    DATABASE_URL=your_database_url
    ENV=development
    ```

### Running the Application

1. **Start the FastAPI server:**

    ```sh
    uvicorn app.main:app --reload
    ```

2. **Access the application:**

    Open your browser and go to `http://127.0.0.1:8000`.

### Deployment

1. **Login to Heroku:**

    ```sh
    heroku login
    ```

2. **Create a new Heroku app:**

    ```sh
    heroku create your-app-name
    ```

3. **Set environment variables on Heroku:**

    ```sh
    heroku config:set DATABASE_URL=your_database_url
    heroku config:set ENV=production
    ```

4. **Deploy to Heroku:**

    ```sh
    git push heroku main
    ```

5. **Open the deployed app:**

    ```sh
    heroku open
    ```

## API Endpoints

### Webhook Order Updates

- **URL:** `/angelone/webhook/orders/updates`
- **Method:** `POST`
- **Description:** Receives order updates from AngelOne.

### NFO Trading

- **URL:** `/angelone/nfo`
- **Method:** `POST`
- **Description:** Handles NFO trading signals.

## Contributing

1. **Fork the repository**
2. **Create a new branch (`git checkout -b feature-branch`)**
3. **Commit your changes (`git commit -am 'Add new feature'`)**
4. **Push to the branch (`git push origin feature-branch`)**
5. **Create a new Pull Request**

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Acknowledgements

- [FastAPI](https://fastapi.tiangolo.com/)
- [Heroku](https://www.heroku.com/)
- [SQLAlchemy](https://www.sqlalchemy.org/)
