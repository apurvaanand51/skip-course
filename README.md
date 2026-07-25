# This tool is developed by Apurva Anand.
## Raise an issue for any kind of help and star this repository so you don't forget the solution! 😉

# Manual

- Requirements - 
    - Python (install python if it's not installed on your pc)

## step 1 - git clone https://github.com/apurvaanand51/skip-course 
(if you do not have git installed on you pc you can download zip file by clicking on the code button and then unzip it)
## step 2 - right click on folder and open in terminal
## step 3 - pip install -r requirements.txt
## step 4 - python -m apurva.main (name of course extracted from link)
 - it will then try to fetch the cookies from you browser if it is unable to do so it will throw an error

 ## manual cookie setup - 
    - go to C drive then Users then select your username there you will see a folder name ".skip-course" in that folder you will see config.json file in that file copy the following content - 
    
    {
        "cookies": {
            "CAUTH": "...",
            "CSRF3-Token": "...",
            "__204u": "..."
        }
    }

    then go to browser open coursera open console (ctrl + shift + i) go to application on left side find cookies. there you will find you cookies copy and paste csrf toker, __204u and CAUTH one by one, save and exit the file.

    run this command again and all your lecture will be completed in minutes.

## python -m apurva.main (name of course extraxted from link)
