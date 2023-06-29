import asyncio
import json

import aioredis
import httpx

from app.core.config import get_config


async def update_expiry_list(
    config,
    dpNm,
):
    async_redis_client = aioredis.StrictRedis.from_url(
        config.data["cache_redis"]["url"], encoding="utf-8", decode_responses=True
    )

    # for BankNifty and Nifty dpNm is INDX OPT
    # analyse the expiry list for other symbol
    headers = {
        "appidkey": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhcHAiOjEsImZmIjoiVyIsImJkIjoid2ViLXBjIiwibmJmIjoxNTc5MjQxODMyLCJzcmMiOiJlbXRtdyIsImF2IjoiMS4wLjAuNCIsImFwcGlkIjoiNGZlNjhiNzUzNjc4NGUzNDA3YzNlY2YxOWJlN2M0YWQiLCJpc3MiOiJlbXQiLCJleHAiOjE2MTA3NzgxMzIsImlhdCI6MTU3OTI0MjEzMn0.IR-PKf1Jjr69bsERFmMeuZrZ2RafBDiTGgKA6Ygofdo"
    }
    async with httpx.AsyncClient() as client:
        res = await client.get(
            "https://ewin.edelweiss.in/edelmw-content/content/search/symbolexpiry",
            headers=headers,
        )

        try:
            expiry_list = list(
                filter(
                    lambda data: data["dpNm"] == dpNm,
                    res.json()["data"]["validExpiry"],
                )
            )[0]["exp"][0]["expLst"]

            await async_redis_client.set("expiry_list", json.dumps(expiry_list))
            return expiry_list
        except Exception as e:
            # push error to sentry
            # TODO: setup sentry
            # capture_exception(Exception(f"error occured while updating expiry list: {e}"))
            print(f"error occured while updating expiry list: {e}")


if __name__ == "__main__":
    config = get_config()
    asyncio.run(update_expiry_list(config, "INDX OPT"))


# its profiling code
"""

Using `py-spy` on Heroku can be a bit more complicated, as Heroku's ephemeral file system and dyno restrictions might limit how you can profile your application. However, you can still profile your application using `py-spy` on Heroku by following these steps:

1. Add `py-spy` to your `requirements.txt` file to install it as a dependency:

```
py-spy==0.3.12  # Adjust the version number to the latest version
```

2. Create a new file in your project, named `profile_py-spy.sh`, with the following content:

```bash
#!/bin/bash

APP_PID=$(pgrep -f "your_app_name" | head -n 1)

if [ -z "$APP_PID" ]; then
  echo "App is not running."
  exit 1
fi

echo "Profiling process with PID: $APP_PID"

py-spy profile --pid "$APP_PID" --duration 60 --format speedscope --file /tmp/profile_output.speedscope
echo "Uploading profiling data to a temporary file storage service..."
curl -s --upload-file /tmp/profile_output.speedscope https://file.io/?expires=1d
```

Replace `your_app_name` with the name of your application or the script that starts your application. This script will profile your application for 60 seconds and upload the profiling data to [file.io](https://file.io), a temporary file storage service. You can adjust the duration and file format as needed.

3. Modify your `Procfile` to include the profiling script. Add the following line to your `Procfile`:

```
profile: bash profile_py-spy.sh
```

This will create a new process type named `profile` that will run the profiling script.

4. Deploy your application to Heroku by pushing your changes:

```bash
git add requirements.txt Procfile profile_py-spy.sh
git commit -m "Add py-spy and profiling script"
git push heroku master
```

5. Run the profiling script on a one-off dyno using the Heroku CLI:

```bash
heroku run profile
```

This will start a new dyno, run the profiling script, and print a link to download the profiling data. Open the link in your browser to download the `.speedscope` file.

6. Analyze the profiling data using the [Speedscope](https://www.speedscope.app/) web application. Open the Speedscope website, click "Browse..." or "Choose File," and select the downloaded `.speedscope` file to visualize the profiling data.

Keep in mind that profiling a running application might have some performance impact. It's recommended to profile your application in a staging environment or during low-traffic periods to minimize the impact on users.

"""
