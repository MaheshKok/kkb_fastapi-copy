# FastAPI Trading Application

This is a FastAPI application for managing trading operations in the Indian futures and options market. The application is deployed on Heroku.

## Features

- Modularized trading operations
- Improved logging and error handling
- Enhanced readability and maintainability
- Type hints for better code clarity
- Environment-specific configurations


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
