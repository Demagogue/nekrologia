import os 
from .auth import login_required
from flask import g, current_app, Blueprint, request, render_template, url_for, session, send_file, jsonify, Response
from nekrologia.db import get_db 
from nekrologia.cache import get_cache, get_cached_resource, update_cache
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps 

bp = Blueprint('api', __name__)

DEFAULT_RES_PATH = "/home/mrybicki/Project/necrologia/nekrologia/res/osoba/"


@bp.route('/api/grave/<int:grave_id>', methods = ['GET'])
def person_descr(grave_id):
    path = os.path.join(DEFAULT_RES_PATH, str(grave_id) + '.html')
    if not os.path.exists(path):
        path = os.path.join(DEFAULT_RES_PATH, 'error.html')
    with open(path, 'r') as fi:
        return Response(fi.read(), mimetype = "text/html")
    
@bp.route('/api/list/<string:tablename>', methods = ['GET', 'POST'])
def list_resource(tablename):
    if tablename not in ('user', 'grave', 'cementary'):
        return jsonify({'status_msg' : 'Unkown resource %s' % (tablename, )})
    res = get_db().execute('SELECT * FROM {}'.format(tablename)).fetchall()
    return jsonify({ row['id'] : dict(row) for row in res })
 
@bp.route('/api/show/<string:tablename>/<int:uid>', methods = ['GET'])
def show(tablename, uid):
    if request.method == 'GET':
        if tablename not in ('grave', 'cementary', 'user'):
            return jsonify({'status_msg' : 'Table: ' + tablename + " is unknown"})
        data = get_db().execute('SELECT * FROM {} WHERE id = ?'.format(tablename), (uid, )).fetchone()
        return jsonify(dict(data))

def api_create_helper(target, fields, data):
    db = get_db()
    # INSERT INTO grave(id, ...) VALUES (id, ...)
    sql = "INSERT INTO {}({}) VALUES ({})".format(target, ', '.join(fields), ', '.join(['?']*len(fields)))
    print(sql)
    try:
        placeholders = []
        for key in fields:
            if key == 'password_hash':
                placeholders.append(generate_password_hash(data['password']))
            placeholders.append(data[key])
    except KeyError as ke:
        return {'status_msg' : 'Missing field :: ' + str(ke)}

    db.execute(sql, placeholders)
    db.commit() 
    if target == 'grave':
        grave = db.execute('SELECT id FROM {} WHERE name=? AND surname=?'.format(target), (data['name'], data['surname'])).fetchone()  
        return {'status_msg' : 'ok', 'id' : grave['id'] }
    return {"status_msg": "ok"}

@bp.route('/api/create/<string:tablename>', methods = ['POST'])
def create(tablename):
    json_data = request.get_json()
    if json_data is None:
        return jsonify({'status_msg': 'Ajax error - no json on server'})
    if tablename == 'grave':
        fields = ("name", "surname", "title", "full_name_with_title", "date_of_birth", 
            "date_of_death", "cementary_id", "gps_lon", "gps_lat")
        grave = get_db().execute('SELECT id FROM grave WHERE name=? AND surname=?', (json_data['name'], json_data['surname'])).fetchone()  
        print(str(grave))
        if grave is not None:
            return jsonify({'status_msg':  'Already exist'})
        result = api_create_helper("grave", fields, json_data)
        return jsonify(result)
    elif tablename == 'cementary':
        fields = ("full_name", "full_address", "city")
        print(json_data)
        cementary = get_db().execute('SELECT id FROM cementary WHERE full_name=? AND city=?', (json_data['full_name'], json_data['city'])).fetchone()  
        if cementary is not None:
            return jsonify({'status_msg':  'Already exist'})
        
        return jsonify(api_create_helper("cementary", fields, json_data))
    elif tablename == 'user':
        fields = ("username", "email", "password_hash", "admin_permit", "activated")
        if "password" in json_data:
            json_data['password_hash'] = generate_password_hash(json_data["password"])
        return jsonify(api_create_helper('users', fields, json_data))
    elif tablename == 'description':
        user_id = json_data['id']
        data = json_data['description']
        path = os.path.join(DEFAULT_RES_PATH, str(user_id) + '.html')
        with open(path, 'w') as fi:
            fi.write(data)
        return jsonify({'status_msg' : 'ok', 'id': user_id})    
    else:
        return jsonify({ "status_msg" : "Unkown resource " + tablename})

def api_update_helper(target, data, fields):
    out = { k : v for k,v in data.items() if k in fields and v != None }
    
    if 'password' in fields and 'password' in data:
        out['password_hash'] = generate_password_hash(data['password'])    

    kv = list(out.items())
    keys = list(item[0] for item in kv)
    columns = ', '.join([key + ' = ?' for key in keys])
    
    vals = list(item[1] for item in kv)
    
    vals.append(id)
    sql = 'UPDATE {} SET {} WHERE id=?'.format(target, columns)
    db = get_db()
    db.execute(sql, vals)
    db.commit()
    return {"status_msg" : "ok"} 


@bp.route('/api/update/<string:param>', methods = ['POST'])
def update(param):
    json_data = request.get_json()
    if json_data == None:
        return jsonify({'status_msg' : "AJAX problem -- json not visible for server"})
    
    target = json_data.get('id', None)
    
    if target == None:
        return jsonify({'status_msg' : "key(id) not specified"})
    if param == 'grave':
        fields = ("name", "surname", "title", "full_name_with_title", "date_of_birth", 
            "date_of_death", "cementary_id", "gps_lon", "gps_lat")
        result = api_update_helper('grave', json_data, fields)
    elif param == 'user':
        fields = ("username", "email", "password_hash", "admin_permit", "activated")
        if "password" in json_data:
            json_data['password_hash'] = generate_password_hash(json_data["password"])
        if ("admin_permit" in json_data or "activated" in json_data) and not g.admin:
            result = { "status_msg" : "Niepoprawna operacja na koncie użytkownika"}
        else: 
        result = api_update_helper('user', json_data, fields)
    elif param == 'cementary':
        fields = ("full_name", "full_address", "city")
        result = api_update_helper('cementary', request.json, fields)
    elif param == 'description':
        user_id = json_data['id']
        data = json_data['description']
        path = os.path.join(DEFAULT_RES_PATH, str(user_id) + '.html')
        with open(path, 'w') as fi:
            fi.write(data)
        result = {'status_msg' : 'ok', 'id': user_id}
    else:
        print("Bad Request :: {} => {!r}".format(param, request.json))
        result = { 'status_msg' : 'incorrect param specified', 'param' : param }
    return jsonify(result)

@bp.route('/api/remove/<string:param>', methods = ['POST'])
def remove(param):
    if param not in ("cementary", "user", "grave", "description"):
        return jsonify(err("Unkown param: {}".format(param)))
    if param == "user":
        if not g.admin:
            return jsonify(err("Tylko admin może usuwać użytkowników. Jeśli chcesz usunąć konto skorzystaj z panelu Moje Konto"))
        else:
            sql = "DELETE FROM user WHERE id=?;"
            db = get_db()
            db.execute(sql, request.json.get("id"))
            db.commit()
            return jsonify({"status_msg" : "OK"})
    elif param == "grave":
            sql = "DELETE FROM grave WHERE id=?;"
            db = get_db()
            db.execute(sql, request.json.get("id"))
            db.commit()
            return jsonify({"status_msg" : "OK"})

            



@bp.route('/api/image', methods = ['GET'])
def get_real_image_href():
    if request.method == 'GET':
        userid = request.args.get('userid')
        result = get_db().select('SELECT img_path FROM image WHERE userid = ?', (userid, )).fetchone()
        return 