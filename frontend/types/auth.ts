export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
}

export interface LoginCredentials {
  email: string;
  password: string;
}
