# 필요한 라이브러리들을 가져옵니다
from fastapi import FastAPI, HTTPException, Request, Form, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
import httpx
from typing import List, Dict, Optional
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import hashlib
import secrets
import time
from datetime import datetime, timedelta

# from auth_routes import auth_router  # 인증 관련 라우터 가져오기

from helpers import hash_password, generate_token  # 유틸리티 함수들 가져오기

templates = Jinja2Templates(directory="templates")

# FastAPI 애플리케이션 인스턴스 생성
app = FastAPI(title="부트캠프 ChatGPT API 서버", version="1.0.0")

# app.include_router(auth_router, prefix="/api/auth", tags=["auth"])  # 인증 관련 라우터 등록

# 부트캠프 API 엔드포인트 URL
BOOTCAMP_API_URL = "https://dev.wenivops.co.kr/services/openai-api"

# 🆕 메모리 저장소 (딕셔너리)
users_db = {}  # {user_id: user_data}
tokens_db = {}  # {token: user_id}
user_activities = {}  # {user_id: [activities]}
user_chat_history = {}  # {user_id: [chat_messages]} 🆕 채팅 내역 저장소
user_selected_habits = {}  # {user_id: selected_habit_data} 🆕 선택된 습관 저장소

# Security
security = HTTPBearer()

# 🆕 인증 관련 모델들
class UserRegister(BaseModel):
    name: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserProfile(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None

class ActivityLog(BaseModel):
    activity: str
    timestamp: str
    category: Optional[str] = None
    habit: Optional[str] = None

class ChatMessage(BaseModel):
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: str

class ChatHistoryRequest(BaseModel):
    message: str
    selected_habit: Optional[Dict] = None

class ChatHistoryResponse(BaseModel):
    success: bool
    response: str
    chat_history: List[Dict]
    usage: Dict = {}

# 기존 모델들
class Message(BaseModel):
    role: str
    content: str

class SimpleChatRequest(BaseModel):
    message: str
    system_message: str = "You are a helpful assistant."

class ConversationRequest(BaseModel):
    messages: List[Message]

class ChatResponse(BaseModel):
    response: str
    usage: Dict

# 🆕 아주 작은 습관 관련 모델들
class HabitRequest(BaseModel):
    goal: str  # health, productivity, stress, energy

class QARequest(BaseModel):
    question: str
    category: Optional[str] = None
    habitType: Optional[str] = None
    requestType: Optional[str] = "normal"

class HabitResponse(BaseModel):
    success: bool
    recommendations: List[Dict] = []
    answer: str = ""
    usage: Dict = {}

# 🆕 유틸리티 함수들
def hash_password(password: str) -> str:
    """비밀번호 해시화"""
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token() -> str:
    """토큰 생성"""
    return secrets.token_urlsafe(32)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """현재 사용자 확인"""
    token = credentials.credentials
    user_id = tokens_db.get(token)
    
    if not user_id or user_id not in users_db:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다")
    
    return users_db[user_id]

def optional_auth(authorization: Optional[str] = Header(None)):
    """선택적 인증 (토큰이 없어도 됨)"""
    if not authorization:
        return None
    
    try:
        token = authorization.replace("Bearer ", "")
        user_id = tokens_db.get(token)
        return users_db.get(user_id) if user_id else None
    except:
        return None

# 🆕 인증 API 엔드포인트들
@app.post("/api/auth/register")
async def register_user(user_data: UserRegister):
    """회원가입"""
    
    # 이메일 중복 확인
    for user in users_db.values():
        if user["email"] == user_data.email:
            raise HTTPException(status_code=400, detail="이미 존재하는 이메일입니다")
    
    # 사용자 생성
    user_id = f"user_{int(time.time())}_{len(users_db)}"
    hashed_password = hash_password(user_data.password)
    
    user = {
        "id": user_id,
        "name": user_data.name,
        "email": user_data.email,
        "password": hashed_password,
        "joinDate": datetime.now().strftime("%Y-%m-%d"),
        "createdAt": datetime.now().isoformat()
    }
    
    users_db[user_id] = user
    user_activities[user_id] = []
    user_chat_history[user_id] = []  # 🆕 채팅 내역 초기화
    user_selected_habits[user_id] = {}  # 🆕 선택된 습관 초기화
    
    # 토큰 생성
    token = generate_token()
    tokens_db[token] = user_id
    
    # 비밀번호 제외하고 반환
    user_response = {k: v for k, v in user.items() if k != "password"}
    
    return {
        "success": True,
        "message": "회원가입이 완료되었습니다",
        "token": token,
        "user": user_response
    }

@app.post("/api/auth/login")
async def login_user(login_data: UserLogin):
    """로그인"""
    
    hashed_password = hash_password(login_data.password)
    
    # 사용자 찾기
    user = None
    user_id = None
    for uid, user_data in users_db.items():
        if user_data["email"] == login_data.email and user_data["password"] == hashed_password:
            user = user_data
            user_id = uid
            break
    
    if not user:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")
    
    # 토큰 생성
    token = generate_token()
    tokens_db[token] = user_id
    
    # 비밀번호 제외하고 반환
    user_response = {k: v for k, v in user.items() if k != "password"}
    
    return {
        "success": True,
        "message": "로그인이 완료되었습니다",
        "token": token,
        "user": user_response
    }

@app.post("/api/auth/logout")
async def logout_user(current_user: dict = Depends(get_current_user), credentials: HTTPAuthorizationCredentials = Depends(security)):
    """로그아웃"""
    
    token = credentials.credentials
    
    # 토큰 삭제
    if token in tokens_db:
        del tokens_db[token]
    
    return {
        "success": True,
        "message": "로그아웃이 완료되었습니다"
    }

# 🆕 채팅 관련 API
@app.post("/api/chat/send")
async def send_chat_message(request: ChatHistoryRequest, current_user: dict = Depends(get_current_user)):
    """채팅 메시지 전송 및 내역 저장"""
    
    user_id = current_user["id"]
    
    # 사용자별 채팅 내역 초기화 (필요시)
    if user_id not in user_chat_history:
        user_chat_history[user_id] = []
    
    # 선택된 습관 저장 (있는 경우)
    if request.selected_habit:
        user_selected_habits[user_id] = request.selected_habit
    
    # 사용자 메시지 저장
    user_message = {
        "role": "user",
        "content": request.message,
        "timestamp": datetime.now().isoformat()
    }
    user_chat_history[user_id].append(user_message)
    
    try:
        # 시스템 메시지 구성
        system_message = {
            "role": "system",
            "content": """당신은 『아주 작은 습관(Atomic Habits)』 전문가이자 친근한 습관 코치입니다. 

다음 원칙들을 기반으로 조언해주세요:
1. 습관은 작게 시작해야 합니다 (2분 규칙)
2. 환경을 디자인하세요 (좋은 습관은 보이게, 나쁜 습관은 숨기게)
3. 습관 쌓기 (기존 습관에 새 습관을 연결)
4. 즉각적 보상을 만드세요
5. 완벽하지 않아도 계속하는 것이 중요합니다

사용자와 자연스럽고 친근한 대화를 나누면서 실용적이고 즉시 실행 가능한 조언을 해주세요. 답변은 따뜻하고 격려하는 톤으로 해주세요."""
        }
        
        # 선택된 습관 정보 추가 (있는 경우)
        if user_id in user_selected_habits and user_selected_habits[user_id]:
            habit_info = user_selected_habits[user_id]
            system_message["content"] += f"\n\n현재 사용자가 관심 있는 습관: {habit_info.get('title', '')} - {habit_info.get('description', '')}"
        
        # 최근 채팅 내역 포함 (최대 20개)
        recent_messages = user_chat_history[user_id][-20:]
        messages = [system_message] + recent_messages
        
        # OpenAI API 호출
        async with httpx.AsyncClient() as client:
            response = await client.post(
                BOOTCAMP_API_URL,
                json=messages,
                timeout=30.0
            )
            response.raise_for_status()
            response_data = response.json()
            
            ai_response = response_data["choices"][0]["message"]["content"]
            
            # AI 응답 저장
            ai_message = {
                "role": "assistant",
                "content": ai_response,
                "timestamp": datetime.now().isoformat()
            }
            user_chat_history[user_id].append(ai_message)
            
            # 활동 기록
            if user_id not in user_activities:
                user_activities[user_id] = []
            
            activity_record = {
                "activity": "chat_conversation",
                "timestamp": datetime.now().isoformat(),
                "category": "chat",
                "habit": "habit_coaching",
                "question": request.message[:100] + "..." if len(request.message) > 100 else request.message,
                "recordedAt": datetime.now().isoformat()
            }
            user_activities[user_id].append(activity_record)
            
            return {
                "success": True,
                "response": ai_response,
                "chat_history": user_chat_history[user_id],
                "usage": response_data["usage"]
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"채팅 처리 중 오류: {str(e)}")

@app.get("/api/chat/history")
async def get_chat_history(current_user: dict = Depends(get_current_user)):
    """사용자 채팅 내역 조회"""
    
    user_id = current_user["id"]
    chat_history = user_chat_history.get(user_id, [])
    selected_habit = user_selected_habits.get(user_id, {})
    
    return {
        "success": True,
        "chat_history": chat_history,
        "selected_habit": selected_habit,
        "total_messages": len(chat_history)
    }

@app.delete("/api/chat/clear")
async def clear_chat_history(current_user: dict = Depends(get_current_user)):
    """채팅 내역 초기화"""
    
    user_id = current_user["id"]
    user_chat_history[user_id] = []
    user_selected_habits[user_id] = {}
    
    return {
        "success": True,
        "message": "채팅 내역이 초기화되었습니다"
    }

@app.post("/api/habits/select")
async def select_habit(habit_data: dict, current_user: dict = Depends(get_current_user)):
    """습관 선택 저장"""
    
    user_id = current_user["id"]
    user_selected_habits[user_id] = habit_data
    
    # 활동 기록
    if user_id not in user_activities:
        user_activities[user_id] = []
    
    activity_record = {
        "activity": "habit_selected",
        "timestamp": datetime.now().isoformat(),
        "category": habit_data.get("category", ""),
        "habit": habit_data.get("title", ""),
        "recordedAt": datetime.now().isoformat()
    }
    user_activities[user_id].append(activity_record)
    
    return {
        "success": True,
        "message": "습관이 선택되었습니다",
        "selected_habit": habit_data
    }

@app.get("/api/user/profile")
async def get_user_profile(current_user: dict = Depends(get_current_user)):
    """사용자 프로필 조회"""
    
    user_response = {k: v for k, v in current_user.items() if k != "password"}
    
    return {
        "success": True,
        "user": user_response
    }

@app.put("/api/user/profile")
async def update_user_profile(profile_data: UserProfile, current_user: dict = Depends(get_current_user)):
    """사용자 프로필 업데이트"""
    
    user_id = current_user["id"]
    
    # 이메일 중복 확인 (다른 사용자가 사용 중인지)
    if profile_data.email:
        for uid, user in users_db.items():
            if uid != user_id and user["email"] == profile_data.email:
                raise HTTPException(status_code=400, detail="이미 사용 중인 이메일입니다")
    
    # 프로필 업데이트
    if profile_data.name:
        users_db[user_id]["name"] = profile_data.name
    if profile_data.email:
        users_db[user_id]["email"] = profile_data.email
    
    users_db[user_id]["updatedAt"] = datetime.now().isoformat()
    
    user_response = {k: v for k, v in users_db[user_id].items() if k != "password"}
    
    return {
        "success": True,
        "message": "프로필이 업데이트되었습니다",
        "user": user_response
    }

@app.post("/api/user/activity")
async def log_user_activity(activity: ActivityLog, current_user: dict = Depends(get_current_user)):
    """사용자 활동 기록"""
    
    user_id = current_user["id"]
    
    if user_id not in user_activities:
        user_activities[user_id] = []
    
    activity_record = {
        "activity": activity.activity,
        "timestamp": activity.timestamp,
        "category": activity.category,
        "habit": activity.habit,
        "recordedAt": datetime.now().isoformat()
    }
    
    user_activities[user_id].append(activity_record)
    
    return {
        "success": True,
        "message": "활동이 기록되었습니다",
        "activity": activity_record
    }

@app.get("/api/user/activities")
async def get_user_activities(current_user: dict = Depends(get_current_user)):
    """사용자 활동 내역 조회"""
    
    user_id = current_user["id"]
    activities = user_activities.get(user_id, [])
    
    return {
        "success": True,
        "activities": activities,
        "total": len(activities)
    }

@app.post("/chat/conversation", response_model=ChatResponse)
async def conversation_chat(request: ConversationRequest):
    """대화 맥락 유지 채팅"""
    messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]

    if not any(msg["role"] == "system" for msg in messages):
        messages.insert(0, {"role": "system", "content": "You are a helpful assistant."})

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(BOOTCAMP_API_URL, json=messages, timeout=30.0)
            response.raise_for_status()
            response_data = response.json()

            return ChatResponse(
                response=response_data["choices"][0]["message"]["content"],
                usage=response_data["usage"]
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

# 🆕 습관 관련 API (인증 선택적)
@app.post("/api/habits/qa")
async def habit_qa(request: QARequest, current_user: Optional[dict] = Depends(optional_auth)):
    """습관 관련 Q&A"""
    
    # 사용자별 맞춤 시스템 메시지
    base_system_message = """
    당신은 『아주 작은 습관(Atomic Habits)』 책의 내용을 바탕으로 조언하는 습관 코치입니다. 
    다음 원칙들을 기반으로 답변해주세요:
    
    1. 습관은 작게 시작해야 합니다 (2분 규칙)
    2. 환경을 디자인하세요 (좋은 습관은 보이게, 나쁜 습관은 숨기게)
    3. 습관 쌓기 (기존 습관에 새 습관을 연결)
    4. 즉각적 보상을 만드세요
    5. 완벽하지 않아도 계속하는 것이 중요합니다
    
    실용적이고 즉시 실행 가능한 조언을 해주세요.
    """
    
    # 요청 타입에 따른 메시지 조정
    if request.requestType == "alternative":
        system_message = base_system_message + "\n\n이번에는 이전과 다른 창의적이고 새로운 방법들을 제안해주세요."
    else:
        system_message = base_system_message
    
    # 사용자가 로그인한 경우 개인화
    user_context = ""
    if current_user:
        user_context = f"\n\n[사용자 정보: {current_user['name']}님을 위한 맞춤 조언]"
        system_message += user_context
    
    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": request.question}
    ]

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(BOOTCAMP_API_URL, json=messages, timeout=30.0)
            response.raise_for_status()
            response_data = response.json()
            
            if not response_data["choices"]:
                raise HTTPException(status_code=500, detail="응답이 비어 있습니다.")
            
            # 사용자 활동 기록 (로그인한 경우)
            if current_user:
                try:
                    user_id = current_user["id"]
                    if user_id not in user_activities:
                        user_activities[user_id] = []
                    
                    activity_record = {
                        "activity": "habit_qa_request",
                        "timestamp": datetime.now().isoformat(),
                        "category": request.category,
                        "habit": request.habitType,
                        "question": request.question[:100] + "..." if len(request.question) > 100 else request.question,
                        "recordedAt": datetime.now().isoformat()
                    }
                    user_activities[user_id].append(activity_record)
                except Exception as log_error:
                    print(f"활동 기록 중 오류: {log_error}")
            
            return {
                "success": True,
                "question": request.question,
                "answer": response_data["choices"][0]["message"]["content"],
                "usage": response_data["usage"],
                "user_authenticated": current_user is not None
            }

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"답변 생성 중 오류: {str(e)}")

# 🆕 목표 카테고리 조회 (인증 불필요)
@app.get("/api/habits/goals")
async def get_available_goals():
    """사용 가능한 목표 카테고리"""
    goals = [
        {"id": "health", "label": "건강 관리", "description": "운동, 식단, 수면 관련 습관"},
        {"id": "productivity", "label": "생산성 향상", "description": "업무 효율성과 시간 관리"},
        {"id": "stress", "label": "스트레스 관리", "description": "정신 건강과 감정 조절"},
        {"id": "energy", "label": "에너지 증진", "description": "활력과 컨디션 개선"}
    ]
    return {"goals": goals}

# 🆕 개발용 엔드포인트들
@app.get("/api/dev/users")
async def get_all_users():
    """개발용: 모든 사용자 조회"""
    users = []
    for user_id, user_data in users_db.items():
        user_safe = {k: v for k, v in user_data.items() if k != "password"}
        users.append(user_safe)
    
    return {
        "users": users,
        "total": len(users),
        "active_tokens": len(tokens_db)
    }

@app.get("/api/dev/activities")
async def get_all_activities():
    """개발용: 모든 활동 조회"""
    return {
        "user_activities": user_activities,
        "total_users": len(user_activities),
        "total_activities": sum(len(activities) for activities in user_activities.values())
    }

@app.delete("/api/dev/reset")
async def reset_database():
    """개발용: 데이터베이스 초기화"""
    global users_db, tokens_db, user_activities, user_chat_history, user_selected_habits
    users_db.clear()
    tokens_db.clear()
    user_activities.clear()
    user_chat_history.clear()  # 🆕 채팅 내역도 초기화
    user_selected_habits.clear()  # 🆕 선택된 습관도 초기화
    
    return {
        "success": True,
        "message": "데이터베이스가 초기화되었습니다"
    }

# 기존 메인 페이지
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    """메인페이지"""
    context = {
        "request": request,
        "title": "아주 작은 습관 GPT",
        "message_count": len(users_db),
        "messages": len(tokens_db)
    }
    return templates.TemplateResponse("index.html", context)

# 🆕 API 상태 확인
@app.get("/api/status")
async def api_status():
    """API 상태 확인"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "users_count": len(users_db),
        "active_sessions": len(tokens_db),
        "total_activities": sum(len(activities) for activities in user_activities.values())
    }

# 서버 실행 코드
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)