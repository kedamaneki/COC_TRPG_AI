from AIworld_Env import DigitalEcosystemEnv

if __name__ == "__main__":
    from stable_baselines3 import PPO

    # 1. テスト用環境の立ち上げ（画面描画をオンにする）
    env = DigitalEcosystemEnv()
    env.render_mode = "human"

    # 2. 初期化
    obs, info = env.reset()

    # ★保存したモデルファイルを読み込みます！
    # 先ほど保存した「ppo_digital_ecosystem.zip」を探して、知能を復元します。
    model = PPO.load("../models/ppo_digital_ecosystem", env=env)
    print("=== 保存されたモデルの読み込みが完了しました ===")

    # 3. 成果の観測（いつでも何回でも見られます）
    for step in range(1000):
        # 読み込んだモデルを使って行動を予測
        action, _states = model.predict(obs, deterministic=False)
        
        # 環境を進める
        obs, reward, terminated, truncated, info = env.step(action.item())
        
        # 画面に表示
        env.render()
        
        if terminated:
            print(f"{step}歩目でエピソード終了（餓死）")
            obs, info = env.reset()