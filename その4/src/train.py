import gymnasium as gym
from gymnasium import spaces
import numpy as np



class DigitalEcosystemEnv(gym.Env):
    def __init__(self, grid_size=10, initial_energy=100):
        # 1. 空間の定義（action_space, observation_space）
        self.grid_size = grid_size
        self.max_energy = initial_energy  
        self.vision_size = 5
        # 2. 環境の初期パラメータ設定
        self.action_space = spaces.Discrete(5)
        self.observation_space = spaces.Dict({
            "vision": spaces.Box(
                low=0, 
                high=2, 
                shape=(self.vision_size, self.vision_size), 
                dtype=np.uint8
            ),
            "energy": spaces.Box(
                low=0, 
                high=self.max_energy, 
                shape=(1,), 
                dtype=np.float32
            )
        })
        pass

    def _get_obs(self):
        # 例：self.grid が環境全体の二次元配列（N x N）
        # 例：self.agent_pos が [x, y] のリスト
        
        x, y = self.agent_pos
        pad_width = self.vision_size // 2  # 5 // 2 = 2マス分を周囲に足す
        
        # マップの周囲を「壁 (1)」でパディングする
        padded_grid = np.pad(
            self.grid, 
            pad_width=pad_width, 
            mode='constant', 
            constant_values=1  # 範囲外はすべて壁として認識させる
        )
        
        # パディングされた配列から 5x5 を切り出す
        # (パディングした分、インデックスがずれるので注意が必要なく、そのまま [y : y+5, x : x+5] で切り抜けます)
        vision = padded_grid[y : y + self.vision_size, x : x + self.vision_size]
        
        # 辞書型で返す
        return {
            "vision": np.array(vision, dtype=np.uint8),
            "energy": np.array([self.energy], dtype=np.float32)
        }

    def reset(self, seed=None, options=None):
            # 1. Gymnasium標準の乱数シード初期化（必須）
            super().reset(seed=seed)

            # 2. エージェントのステータス初期化
            self.energy = self.max_energy
            
            # エージェントをマップの中央に配置
            center = self.grid_size // 2
            self.agent_pos = [center, center] 

            # 3. マップの初期化（すべて0：空白の二次元配列を作る）
            self.grid = np.zeros((self.grid_size, self.grid_size), dtype=np.uint8)

            # 4. 初期リソースのばらまき
            initial_resources = 5  # 最初に配置する数（お好みで調整してください）
            for _ in range(initial_resources):
                self._spawn_resource()

            # 5. 初期状態の観測データを取得
            obs = self._get_obs()

            # Gymnasium v0.26以降のルール： (observation, info) のタプルを返す
            return obs, {}


    def _spawn_resource(self):
        # 1. 現在「0（空白）」になっているマスのインデックス（座標）を全て取得
        empty_cells = np.argwhere(self.grid == 0)

        # 2. 空きマスが1つ以上ある場合のみ処理を行う
        if len(empty_cells) > 0:
            # 3. 空きマスのリストから、ランダムに1つのインデックスを選ぶ
            random_idx = self.np_random.integers(0, len(empty_cells))
            
            # 選ばれた座標を取り出す
            y, x = empty_cells[random_idx]

            # 4. そのマスを「2（リソース）」に書き換える
            self.grid[y, x] = 2

    def step(self, action):
        # 初期化
        reward = 0.0
        terminated = False
        truncated = False
        info = {}

        # 1. 現在の座標を取得
        x, y = self.agent_pos
        dx, dy = 0, 0

        # 行動(action)をベクトルに変換
        if action == 0:   dy = -1  # 上
        elif action == 1: dy = 1   # 下
        elif action == 2: dx = -1  # 左
        elif action == 3: dx = 1   # 右
        # action == 4 (待機) の場合は dx, dy 共に 0

        # 移動先の「候補」座標を計算
        new_x = x + dx
        new_y = y + dy

        # 2. 衝突判定（マップの境界チェック）
        # マップの範囲内 (0 から grid_size-1) に収まっているか確認
        if 0 <= new_x < self.grid_size and 0 <= new_y < self.grid_size:
            # ※もしマップ内に障害物(1)を配置している場合は、ここでさらに
            # `if self.grid[new_y, new_x] != 1:` という判定を追加します
            self.agent_pos = [new_x, new_y]  # 移動成功！座標を更新
        else:
            pass # マップ外に出ようとした場合は移動失敗（座標は更新しない）

        # 3. 基礎代謝（エネルギー消費）と基本報酬
        self.energy -= 1.0  # 動いても待機しても毎ターンエネルギーを消費
        reward += 0.1       # 生存しているだけで与えられる基本報酬

        # 4. リソース獲得判定（移動後の座標でチェック）
        curr_x, curr_y = self.agent_pos
        if self.grid[curr_y, curr_x] == 2:  # 今いるマスがリソース(2)だった場合
            # エネルギーを回復（ただし max_energy を超えないようにする）
            self.energy = min(self.energy + 20.0, self.max_energy)
            
            # 食べたリソースをマップから消す（空白=0にする）
            self.grid[curr_y, curr_x] = 0
            
            reward += 5.0  # リソース獲得の大きな報酬
            
            # 新しいリソースをマップのどこかに再配置する（関数を呼び出す想定）
            self._spawn_resource() 

        # 5. 死亡判定
        if self.energy <= 0:
            self.energy = 0
            terminated = True  # エピソード終了フラグを立てる
            reward -= 10.0     # 死亡時の大きなペナルティ

        # 6. 最新の観測データを取得（先ほど作ったメソッドを使用）
        obs = self._get_obs()

        # Gymnasiumのルールに従って5つの値を返す
        return obs, reward, terminated, truncated, info

    def render(self):
            # 画面描画用のモードが設定されているか確認
            if getattr(self, 'render_mode', None) == "human":
                import pygame
                
                # 初回呼び出し時にPygameのウィンドウを準備
                if not hasattr(self, 'window') or self.window is None:
                    pygame.init()
                    self.cell_size = 40  # 1マスのサイズ（40ピクセル）
                    window_size = self.grid_size * self.cell_size
                    self.window = pygame.display.set_mode((window_size, window_size))
                    pygame.display.set_caption("AI Sandbox")
                    self.clock = pygame.time.Clock()

                # 画面を黒(0, 0, 0)でリセット
                self.window.fill((0, 0, 0))

                # グリッド上の全マスを走査して描画
                for y in range(self.grid_size):
                    for x in range(self.grid_size):
                        # マスの四角形を定義
                        rect = pygame.Rect(x * self.cell_size, y * self.cell_size, self.cell_size, self.cell_size)
                        
                        # リソース(2)があるマスは緑色で塗りつぶす
                        if self.grid[y, x] == 2:
                            pygame.draw.rect(self.window, (0, 255, 0), rect)
                        
                        # マスの枠線を暗いグレーで描画（太さ1）
                        pygame.draw.rect(self.window, (40, 40, 40), rect, 1)

                # エージェントを描画（青い円）
                agent_x, agent_y = self.agent_pos
                center_x = agent_x * self.cell_size + self.cell_size // 2
                center_y = agent_y * self.cell_size + self.cell_size // 2
                pygame.draw.circle(self.window, (0, 150, 255), (center_x, center_y), self.cell_size // 3)

                # 画面の更新を反映
                pygame.event.pump()
                pygame.display.update()
                
                # 1秒間に描画するフレーム数(FPS)を制限し、人間が目で追えるスピードにする
                self.clock.tick(10)

if __name__ == "__main__":
    from stable_baselines3 import PPO

    # 学習用環境の立ち上げ（描画はオフ）
    env = DigitalEcosystemEnv()

    # AIモデルの作成
    model = PPO("MultiInputPolicy", env, verbose=1)

    # 20万ステップの学習
    print("=== 学習を開始します ===")
    model.learn(total_timesteps=200000)
    print("=== 学習完了！ ===")

    # ★ここでモデルをファイルに保存します！
    # 実行すると、同じフォルダ内に「ppo_digital_ecosystem.zip」というファイルが生成されます。
    model.save("ppo_digital_ecosystem")
    print("=== モデルの保存が完了しました ===")