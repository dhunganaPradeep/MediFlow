# MediFlow: Simple Explanation

## What is this project?
MediFlow is a data platform designed for hospitals and healthcare systems. Its main goal is to **predict future demand for healthcare resources**, such as how many beds will be occupied, how long patients will wait in the emergency room (ER), and how many ambulances will be needed. 

By forecasting these needs before they happen, hospitals can avoid staffing shortages and handle patient surges smoothly instead of reacting when it's already too late.

## Who can use this and what are the Use Cases?
The project comes with three ready-to-use dashboards tailored for specific roles:
1. **Hospital Operations / Administrators:** To oversee overall bed occupancy, plan staffing budgets, and ensure the hospital runs efficiently.
2. **ER Coordinators:** To monitor live emergency room wait times and call in backup staff if a surge is predicted in the next few hours.
3. **Strategic Health Planners:** To analyze long-term trends, like seasonal disease waves, to plan for facility expansions or new ambulance routes.

## Where does the dataset come from?
The project currently uses **synthetic (fake but highly realistic) data**. 
Instead of risking the exposure of real patient information, the system uses mathematical models and statistical rules to simulate real-world patient arrivals. This is combined with actual, real-world weather data (from Open-Meteo) and public health data (from CDC/WHO) to make the simulations behave exactly like a real hospital would during different seasons or weather events.

## Components Used and What They Do

This project uses modern, industry-standard tools linked together:

- **PostgreSQL (The Database):** Stores all the raw records and the organized historical data.
- **Apache Airflow (The Conductor):** A scheduling tool that runs in the background. It wakes up every hour, gathers new data, checks it for errors, and moves it to the right places.
- **dbt (Data Build Tool):** Cleans up and organizes the raw data inside the database so it's easy to read and analyze.
- **AI/ML Forecasting Models (Prophet, SARIMA, LSTM):** The "brains" that analyze past data to predict the future. They output the predictions for bed occupancy, ER waits, and ambulance demand.
- **Apache Superset (The Dashboard):** The visual interface where users can see charts, graphs, and the AI's predictions. 
- **Keycloak (Identity & Login):** This is the security guard. It handles user logins and makes sure an ER doctor only sees ER data, and a planner sees what they are allowed to see. *(Note: This is likely what you referred to as "keychain").*
- **Grafana & Prometheus (System Monitors):** These tools keep an eye on the software itself, ensuring the servers aren't running out of memory and everything is healthy.
- **HashiCorp Vault (The Safe):** Securely locks away all sensitive passwords, encryption keys, and secrets so they are never exposed in the code.

## Main Functions & Problem Statement

**The Problem:** Hospitals usually only realize they don't have enough beds or staff when the waiting room is already full. Data exists to predict this, but it's usually scattered across different old systems.

**What this project exactly does:**
1. **Collects & Cleans:** It continuously streams in simulated hospital events and weather data.
2. **Learns & Predicts:** It feeds this data into AI models that look at patterns (e.g., "Every time there's a snowstorm on a Monday, ER visits go up by 20%").
3. **Visualizes & Alerts:** It displays these predictions on easy-to-read dashboards and can send alerts if it predicts the ER will be overwhelmed in the next few hours.
