import psycopg2

try:
    conn = psycopg2.connect(dbname='ugurlar', user='openpg', password='openpgpwd', host='localhost')
    cur = conn.cursor()
    cur.execute("UPDATE social_media_message SET ai_processed = True WHERE message_type = 'incoming' AND ai_processed = False;")
    conn.commit()
    print("Successfully marked " + str(cur.rowcount) + " old messages as processed.")
    cur.close()
    conn.close()
except Exception as e:
    print("Failed with openpgpwd:", e)
    try:
        conn = psycopg2.connect(dbname='ugurlar', user='openpg', host='127.0.0.1')
        cur = conn.cursor()
        cur.execute("UPDATE social_media_message SET ai_processed = True WHERE message_type = 'incoming' AND ai_processed = False;")
        conn.commit()
        print("Successfully marked " + str(cur.rowcount) + " old messages as processed.")
        cur.close()
        conn.close()
    except Exception as e2:
        print("Failed without password:", e2)
