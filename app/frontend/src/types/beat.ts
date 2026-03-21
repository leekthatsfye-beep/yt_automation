export interface Beat {
  stem: string;
  filename: string;
  title: string;
  beat_name?: string;
  artist: string;
  description: string;
  tags: string[];
  bpm: number | null;
  key: string | null;
  rendered: boolean;
  has_thumbnail: boolean;
  uploaded: boolean;
  lane?: string | null;
  seo_artist?: string;
  file_size: number;
  modified: string;
  youtube?: {
    videoId: string;
    url: string;
    uploadedAt: string;
    title: string;
    publishAt?: string;
  };
  social?: Record<string, unknown>;
}
